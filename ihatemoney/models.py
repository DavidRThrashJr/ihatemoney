from collections import defaultdict

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy, BaseQuery
from flask import g, current_app

from debts import settle
from sqlalchemy import orm, case
from sqlalchemy.sql import func
from itsdangerous import (
    TimedJSONWebSignatureSerializer,
    URLSafeSerializer,
    BadSignature,
    SignatureExpired,
)

db = SQLAlchemy()


class Project(db.Model):
    class ProjectQuery(BaseQuery):
        def get_by_name(self, name):
            return Project.query.filter(Project.name == name).one()

    id = db.Column(db.String(64), primary_key=True)

    name = db.Column(db.UnicodeText)
    password = db.Column(db.String(128))
    contact_email = db.Column(db.String(128))
    members = db.relationship("Person", backref="project")
    # each project will be able to decide whether they want to use advanced weighting
    # meaning that they will be able to specify the weight for each member within each bill
    advanced_weighting_enabled = db.Column(db.Boolean, default=False)

    query_class = ProjectQuery

    @property
    def _to_serialize(self):
        obj = {
            "id": self.id,
            "name": self.name,
            "contact_email": self.contact_email,
            "members": [],
            "advanced_weighting_enabled": self.advanced_weighting_enabled,
        }

        balance = self.balance
        for member in self.members:
            member_obj = member._to_serialize
            member_obj["balance"] = balance.get(member.id, 0)
            obj["members"].append(member_obj)

        return obj

    @property
    def active_members(self):
        return [m for m in self.members if m.activated]

    @property
    def balance(self):
        # RAW SQL
        # SELECT
        # person.id as person_id,
        # SUM(CASE
        # WHEN
        # bill.payer_id = person.id
        # THEN
        # bill.amount - (bill.amount / (totalperson.weight)) * (person.weight)
        # ELSE((bill.amount / (totalperson.weight)) * (person.weight) * -1)
        # END) AS
        # balance
        # FROM
        # bill, person, billowers,
        # (SELECT bill.id, sum(billowers.weight) as total
        # FROM
        # bill, person, billowers
        # WHERE
        # bill.id = billowers.bill_id
        # AND
        # person.id = billowers.ower_id
        # AND
        # person.project_id = 1
        # GROUP
        # BY
        # billowers.bill_id) as billweight,
        # (SELECT billowers.bill_id, billowers.ower_id, billowers.weight as total
        # FROM bill, person, billowers
        # WHERE bill.id = billowers.bill_id AND
        # person.id = billowers.ower_id AND
        # person.project_id=1) as billpersonweight,
        # (SELECT billowers.bill_id, sum(person.weight) as weight
        # FROM
        # billowers, person
        # WHERE
        # billowers.ower_id = person.id
        # AND
        # person.project_id = 1
        # GROUP
        # BY
        # billowers.bill_id) as totalperson
        # WHERE
        # bill.id = billowers.bill_id
        # AND
        # bill.id = billweight.id
        # AND
        # bill.id = billpersonweight.bill_id
        # AND
        # person.id = billpersonweight.ower_id
        # AND
        # bill.id = totalperson.bill_id
        # AND
        # person.id = billowers.ower_id
        # group
        # by
        # person.id

        bill_weight = db.session.query(Bill.id.label("bill_id"),
                                       func.sum(BillOwers.weight).label("total"))\
            .join(BillOwers, Person)\
            .filter(db.and_(Bill.id == BillOwers.bill_id,
                            Person.id == BillOwers.ower_id,
                            Project.id == self.id))\
            .group_by(BillOwers.bill_id)\
            .subquery()

        bill_person_weight = db.session.query(BillOwers.bill_id,
                                              BillOwers.ower_id,
                                              BillOwers.weight.label("total"))\
            .join(Bill, Person)\
            .filter(db.and_(Bill.id == BillOwers.bill_id,
                            Person.id == BillOwers.ower_id,
                            Person.project_id == self.id))\
            .subquery()

        total_person = db.session.query(BillOwers.bill_id,
                                        func.sum(Person.weight).label("weight"))\
            .join(BillOwers)\
            .filter(db.and_(BillOwers.ower_id == Person.id,
                            Person.project_id == self.id))\
            .group_by(BillOwers.bill_id)\
            .subquery()

        # will need to have a case statement for self.advanced_weighting_enabled
        # this will toggle between bill_weight.c.total & total_person.c.weight
        # right now we're only using total_person.c.weight

        balances = db.session.query(Person.id.label("person_id"),
                                    case(
                                        [
                                            (
                                                Bill.payer_id == Person.id,
                                                    Bill.amount -
                                                    (Bill.amount / (total_person.c.weight))
                                                    *
                                                    (Person.weight)
                                            ),
                                            (
                                                Bill.payer_id != Person.id,
                                                (
                                                    Bill.amount / (total_person.c.weight) * (
                                                                Person.weight)
                                                )

                                            )
                                        ]
                                    ).label("balance")
                                    )\
            .join(Bill, BillOwers,
                  bill_weight, bill_person_weight, total_person)\
            .filter(db.and_(Bill.id == BillOwers.bill_id,
                            Bill.id == bill_weight.c.bill_id,
                            Bill.id == bill_person_weight.c.bill_id,
                            Person.id == bill_person_weight.c.ower_id,
                            Bill.id == total_person.c.bill_id,
                            Person.id == BillOwers.ower_id))\
            .group_by(Person.id)
        # just testing to match the out put to the unit test: test_project_balance
        # wrong so-far, because the database is not normalized
        print(balances.all())

        balances, should_pay, should_receive = (defaultdict(int) for time in (1, 2, 3))

        # for each person
        for person in self.members:
            # get the list of bills he has to pay
            bills = Bill.query.options(orm.subqueryload(Bill.owers)).filter(
                Bill.owers.contains(person)
            )
            for bill in bills.all():
                if person != bill.payer:
                    share = bill.pay_each() * person.weight
                    should_pay[person] += share
                    should_receive[bill.payer] += share

        for person in self.members:
            balance = should_receive[person] - should_pay[person]
            balances[person.id] = balance
        return balances

    @property
    def members_stats(self):
        """Compute what each member has paid

        :return: one stat dict per member
        :rtype list:
        """
        return [
            {
                "member": member,
                "paid": sum(
                    [bill.amount for bill in self.get_member_bills(member.id).all()]
                ),
                "spent": sum(
                    [
                        bill.pay_each() * member.weight
                        for bill in self.get_bills().all()
                        if member in bill.owers
                    ]
                ),
                "balance": self.balance[member.id],
            }
            for member in self.active_members
        ]

    @property
    def monthly_stats(self):
        """Compute expenses by month

        :return: a dict of years mapping to a dict of months mapping to the amount
        :rtype dict:
        """
        monthly = defaultdict(lambda: defaultdict(float))
        for bill in self.get_bills().all():
            monthly[bill.date.year][bill.date.month] += bill.amount
        return monthly

    @property
    def uses_weights(self):
        return len([i for i in self.members if i.weight != 1]) > 0

    def get_transactions_to_settle_bill(self, pretty_output=False):
        """Return a list of transactions that could be made to settle the bill"""

        def prettify(transactions, pretty_output):
            """ Return pretty transactions
            """
            if not pretty_output:
                return transactions
            pretty_transactions = []
            for transaction in transactions:
                pretty_transactions.append(
                    {
                        "ower": transaction["ower"].name,
                        "receiver": transaction["receiver"].name,
                        "amount": round(transaction["amount"], 2),
                    }
                )
            return pretty_transactions

        # cache value for better performance
        members = {person.id: person for person in self.members}
        settle_plan = settle(self.balance.items()) or []

        transactions = [
            {
                "ower": members[ower_id],
                "receiver": members[receiver_id],
                "amount": amount,
            }
            for ower_id, amount, receiver_id in settle_plan
        ]

        return prettify(transactions, pretty_output)

    def exactmatch(self, credit, debts):
        """Recursively try and find subsets of 'debts' whose sum is equal to credit"""
        if not debts:
            return None
        if debts[0]["balance"] > credit:
            return self.exactmatch(credit, debts[1:])
        elif debts[0]["balance"] == credit:
            return [debts[0]]
        else:
            match = self.exactmatch(credit - debts[0]["balance"], debts[1:])
            if match:
                match.append(debts[0])
            else:
                match = self.exactmatch(credit, debts[1:])
            return match

    def has_bills(self):
        """return if the project do have bills or not"""
        return self.get_bills().count() > 0

    def get_bills(self):
        """Return the list of bills related to this project"""
        return (
            Bill.query.join(Person, Project)
            .filter(Bill.payer_id == Person.id)
            .filter(Person.project_id == Project.id)
            .filter(Project.id == self.id)
            .order_by(Bill.date.desc())
            .order_by(Bill.creation_date.desc())
            .order_by(Bill.id.desc())
        )

    def get_member_bills(self, member_id):
        """Return the list of bills related to a specific member"""
        return (
            Bill.query.join(Person, Project)
            .filter(Bill.payer_id == Person.id)
            .filter(Person.project_id == Project.id)
            .filter(Person.id == member_id)
            .filter(Project.id == self.id)
            .order_by(Bill.date.desc())
            .order_by(Bill.id.desc())
        )

    def get_pretty_bills(self, export_format="json"):
        """Return a list of project's bills with pretty formatting"""
        bills = self.get_bills()
        pretty_bills = []
        for bill in bills:
            if export_format == "json":
                owers = [ower.name for ower in bill.owers]
            else:
                owers = ", ".join([ower.name for ower in bill.owers])

            pretty_bills.append(
                {
                    "what": bill.what,
                    "amount": round(bill.amount, 2),
                    "date": str(bill.date),
                    "payer_name": Person.query.get(bill.payer_id).name,
                    "payer_weight": Person.query.get(bill.payer_id).weight,
                    "owers": owers,
                }
            )
        return pretty_bills

    def remove_member(self, member_id):
        """Remove a member from the project.

        If the member is not bound to a bill, then he is deleted, otherwise
        he is only deactivated.

        This method returns the status DELETED or DEACTIVATED regarding the
        changes made.
        """
        try:
            person = Person.query.get(member_id, self)
        except orm.exc.NoResultFound:
            return None
        if not person.has_bills():
            db.session.delete(person)
            db.session.commit()
        else:
            person.activated = False
            db.session.commit()
        return person

    def remove_project(self):
        db.session.delete(self)
        db.session.commit()

    def generate_token(self, expiration=0):
        """Generate a timed and serialized JsonWebToken

        :param expiration: Token expiration time (in seconds)
        """
        if expiration:
            serializer = TimedJSONWebSignatureSerializer(
                current_app.config["SECRET_KEY"], expiration
            )
            token = serializer.dumps({"project_id": self.id}).decode("utf-8")
        else:
            serializer = URLSafeSerializer(current_app.config["SECRET_KEY"])
            token = serializer.dumps({"project_id": self.id})
        return token

    @staticmethod
    def verify_token(token, token_type="timed_token"):
        """Return the project id associated to the provided token,
        None if the provided token is expired or not valid.

        :param token: Serialized TimedJsonWebToken
        """
        if token_type == "timed_token":
            serializer = TimedJSONWebSignatureSerializer(
                current_app.config["SECRET_KEY"]
            )
        else:
            serializer = URLSafeSerializer(current_app.config["SECRET_KEY"])
        try:
            data = serializer.loads(token)
        except SignatureExpired:
            return None
        except BadSignature:
            return None
        return data["project_id"]

    def __repr__(self):
        return "<Project %s>" % self.name


class Person(db.Model):
    class PersonQuery(BaseQuery):
        def get_by_name(self, name, project):
            return (
                Person.query.filter(Person.name == name)
                .filter(Project.id == project.id)
                .one()
            )

        def get(self, id, project=None):
            if not project:
                project = g.project
            return (
                Person.query.filter(Person.id == id)
                .filter(Project.id == project.id)
                .one()
            )

    query_class = PersonQuery

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(64), db.ForeignKey("project.id"))
    bills = db.relationship("Bill", backref="payer")

    name = db.Column(db.UnicodeText)
    weight = db.Column(db.Float, default=1)
    activated = db.Column(db.Boolean, default=True)

    @property
    def _to_serialize(self):
        return {
            "id": self.id,
            "name": self.name,
            "weight": self.weight,
            "activated": self.activated,
        }

    def has_bills(self):
        """return if the user do have bills or not"""
        bills_as_ower_number = (
            db.session.query(BillOwers)
            .filter(BillOwers.ower_id == self.id)
            .count()
        )
        return bills_as_ower_number != 0 or len(self.bills) != 0

    def __str__(self):
        return self.name

    def __repr__(self):
        return "<Person %s for project %s>" % (self.name, self.project.name)

class BillOwers(db.Model):
    __tablename__ = 'billowers'

    bill_id = db.Column("bill_id", db.Integer, db.ForeignKey("bill.id"), primary_key=True)
    ower_id = db.Column("ower_id", db.Integer, db.ForeignKey("person.id"), primary_key=True)
    # store weight to customize the amount owed for an individual person relative to others within a single bill
    weight = db.Column("weight", db.Integer, default=1)

    bill = db.relationship("Bill", backref=orm.backref('billowers', cascade='all, delete-orphan'))
    ower = db.relationship(Person, backref="billowers")

class Bill(db.Model):
    class BillQuery(BaseQuery):
        def get(self, project, id):
            try:
                return (
                    self.join(Person, Project)
                    .filter(Bill.payer_id == Person.id)
                    .filter(Person.project_id == Project.id)
                    .filter(Project.id == project.id)
                    .filter(Bill.id == id)
                    .one()
                )
            except orm.exc.NoResultFound:
                return None

        def delete(self, project, id):
            bill = self.get(project, id)
            if bill:
                db.session.delete(bill)
            return bill

    query_class = BillQuery

    id = db.Column(db.Integer, primary_key=True)

    payer_id = db.Column(db.Integer, db.ForeignKey("person.id"))
    owers = db.relationship(Person, secondary="billowers")

    amount = db.Column(db.Float)
    date = db.Column(db.Date, default=datetime.now)
    creation_date = db.Column(db.Date, default=datetime.now)
    what = db.Column(db.UnicodeText)
    external_link = db.Column(db.UnicodeText)

    archive = db.Column(db.Integer, db.ForeignKey("archive.id"))

    @property
    def _to_serialize(self):
        return {
            "id": self.id,
            "payer_id": self.payer_id,
            "owers": self.owers,
            "amount": self.amount,
            "date": self.date,
            "creation_date": self.creation_date,
            "what": self.what,
            "external_link": self.external_link,
        }

    def pay_each(self):
        """Compute what each share has to pay"""
        if self.owers:
            weights = (
                db.session.query(func.sum(Person.weight))
                .join("billowers", Bill)
                .filter(Bill.id == self.id)
            ).scalar()
            return self.amount / weights
        else:
            return 0

    def __repr__(self):
        return "<Bill of %s from %s for %s>" % (
            self.amount,
            self.payer,
            ", ".join([o.name for o in self.owers]),
        )


class Archive(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(64), db.ForeignKey("project.id"))
    name = db.Column(db.UnicodeText)

    @property
    def start_date(self):
        pass

    @property
    def end_date(self):
        pass

    def __repr__(self):
        return "<Archive>"
