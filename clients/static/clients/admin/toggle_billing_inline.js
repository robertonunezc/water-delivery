(function() {
    'use strict';
    
    // Wait for both Django admin and jQuery to be available
    function initToggleBilling() {
        var $ = django.jQuery;
        
        // Function to toggle billing inlines visibility
        function toggleBillingInlines() {
            var requiresBillingCheckbox = $('#id_requires_billing');
            if (requiresBillingCheckbox.length === 0) {
                return;
            }
            
            var isChecked = requiresBillingCheckbox.is(':checked');
            
            // Find the billing data inline by looking for the inline with BillingData model
            var billingDataInline = $('#billing_data-group');
            
            // Find the billing frequency inline
            var billingFrequencyInline = $('#billing_frecuency-group');
            const billingDataInfo = $('.tab-billing-inheritance')
            // Toggle visibility with animation
            console.log('Toggling billing inlines. requires_billing:', isChecked);
            if (isChecked) {
                billingDataInline.slideDown(300);
                billingFrequencyInline.slideDown(300);
                billingDataInfo.slideDown(300);
            } else {
                billingDataInline.slideUp(300);
                billingFrequencyInline.slideUp(300);
                billingDataInfo.slideUp(300);
            }
        }
        
        // Initial toggle on page load
        $(document).ready(function() {
            toggleBillingInlines();
            
            // Toggle on checkbox change
            $('#id_requires_billing').on('change', function() {
                toggleBillingInlines();
            });
        });
    }
    
    // Execute when Django admin is ready
    if (typeof django !== 'undefined' && django.jQuery) {
        initToggleBilling();
    } else {
        // Fallback: wait for DOM and django to be available
        document.addEventListener('DOMContentLoaded', function() {
            if (typeof django !== 'undefined' && django.jQuery) {
                initToggleBilling();
            }
        });
    }
})();
