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
            var billingDataInline = $('.inline-group').filter(function() {
                return $(this).find('h2').text().includes('Datos de Facturación') || 
                       $(this).attr('id') && $(this).attr('id').includes('billingdata');
            });
            
            // Find the billing frequency inline
            var billingFrequencyInline = $('.inline-group').filter(function() {
                return $(this).find('h2').text().includes('Frecuencia de Facturación') || 
                       $(this).find('h2').text().includes('Frecuencias de Facturación') ||
                       $(this).attr('id') && $(this).attr('id').includes('clientbillingfrecuency');
            });
            
            // Toggle visibility with animation
            if (isChecked) {
                billingDataInline.slideDown(300);
                billingFrequencyInline.slideDown(300);
            } else {
                billingDataInline.slideUp(300);
                billingFrequencyInline.slideUp(300);
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
