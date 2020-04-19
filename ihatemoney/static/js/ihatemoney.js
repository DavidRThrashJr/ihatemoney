 // Utility to select all or none of the checkboxes in the add_bill form.
function selectCheckboxes(value){
  var els = document.querySelectorAll('[name$=included]');
  for(var i = 0; i < els.length; i++){
    els[i].checked = value;
    els[i].onchange();
  }
}
// In advanced mode, the add_bill form will allow you to set weights for each participant
function ComputeDue() {
  var weights = document.querySelectorAll('[name$=weight]');
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
    personid = weights[i].getAttribute("personid");
    var selector = '[id="due"][personid="'+personid+'"]';
    due = document.querySelector([selector]);
    var selector = '[name$=included][personid="'+personid+'"]';
    included = document.querySelector(selector);
    if (included.checked)
      due.value = (Math.round(((parseInt(bill_amt.value) * (parseInt(weights[i].value)/all_weight)) + Number.EPSILON) * 100) / 100);
    else
      due.value = 0;
  }
}
// weight is set; used when unchecking participant in advanced mode in the add_bill form
function SetWeight(personid) {
  var selector = '[name$="weight"][personid="'+personid+'"]';
  var weight = document.querySelector(selector);

  var selector = '[name$=included][personid="'+personid+'"]';
  included = document.querySelector(selector);

  if (included.checked)
    weight.value = 1;
  else
    weight.value = 0;
  ComputeDue();
}

// weight is set; used when unchecking participant in advanced mode in the add_bill form
function ToggleAdvanced() {
  var toggleSimple = document.getElementById("toggle_advanced_smpl");
  var toggleAdvanced = document.getElementById("toggle_advanced_adv");
  var weightCells = document.querySelectorAll('[id=weight_cell]');
  var weightCol = document.getElementById("weight_col");
  var weights = document.querySelectorAll('[name$=weight]');

  toggleAdvanced.style.display = toggleAdvanced.style.display === 'block' ? 'none' : 'block';
  toggleSimple.style.display = toggleAdvanced.style.display === 'block' ? 'none' : 'block';

  weightCol.style.visibility = weightCol.style.visibility === 'hidden' ? 'visible' : 'hidden';

  for (var i = 0, weightCell; weightCell = weightCells[i]; i++) {
    weightCell.style.visibility = weightCell.style.visibility === 'hidden' ? 'visible' : 'hidden';
  }

  for (var i = 0, weight; weight = weights[i]; i++) {
    weight.style.visibility = weight.style.visibility === 'hidden' ? 'visible' : 'hidden';
  }
}