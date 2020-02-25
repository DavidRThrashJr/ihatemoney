 // Utility to select all or none of the checkboxes in the add_bill form.
function selectCheckboxes(value){
  var els = document.getElementsByName('payed_for');
  for(var i = 0; i < els.length; i++){
    els[i].checked = value;
  }
}
// In advanced mode, the add_bill form will allow you to set weights for each participant
function ComputeDue() {
  var weights = document.getElementsByName('payed_for_weight');
  var bill_amt = document.getElementById('amount');
  var i, all_weight, weight_id, due_id, due;


  // sum up weights for all CHECKED participants
  all_weight = 0;
  for(i = 0; i < weights.length; i++){
    all_weight = parseInt(all_weight) + parseInt(weights[i].value);
  }

  // set amount due for each participant
  for(i = 0; i < weights.length; i++){
    weight_id = weights[i].id;
    due_id = weight_id.replace("payed_for_weight", "payed_for_due");
    payed_for_id = weight_id.replace("payed_for_weight", "payed_for");
    due = document.getElementById(due_id);
    payed_for = document.getElementById(payed_for_id);
    if (payed_for.checked)
      due.value = (parseInt(bill_amt.value) * (parseInt(weights[i].value)/all_weight));
    else
      due.value = 0;
  }
}
// weight is set; used when unchecking participant in advanced mode in the add_bill form
function SetWeight(id) {
  var weight_id = 'payed_for_weight-' + id;
  var weight = document.getElementById(weight_id);

  var payed_for_id = 'payed_for-'+id;
  var payed_for = document.getElementById(payed_for_id);

  if (payed_for.checked)
    weight.value = 1;
  else
    weight.value = 0;
  ComputeDue();
}