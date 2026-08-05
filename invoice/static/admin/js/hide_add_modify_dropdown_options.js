(function () {
      "use strict";
      document.addEventListener("DOMContentLoaded", function () {
  const modifyBillingRecordBtn = document.getElementById(
    "change_id_invoice"
  );
  if (modifyBillingRecordBtn) modifyBillingRecordBtn.hidden = true;
    const addBillingRecordBtn = document.getElementById("add_id_invoice");
    if (addBillingRecordBtn) addBillingRecordBtn.hidden = true;
    
    const modifyOrderBtn = document.getElementById("change_id_order");
    if (modifyOrderBtn) modifyOrderBtn.hidden = true;
    const addOrderBtn = document.getElementById("add_id_order");
    if (addOrderBtn) addOrderBtn.hidden = true;
    
    const viewBillingRecordBtn = document.getElementById("view_id_invoice");
    if (viewBillingRecordBtn) viewBillingRecordBtn.hidden = true;
    const viewOrderBtn = document.getElementById("view_id_order");
    if (viewOrderBtn) viewOrderBtn.hidden = true;
  

      });

})();
