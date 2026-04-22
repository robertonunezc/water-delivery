(function() {
    'use strict';
    
    // Wait for both Django admin and jQuery to be available
    function initBillingFrequencyFieldToggle() {
        var $ = django.jQuery;
        
        // Function to toggle billing frequency fieldsets based on frequency and billing_date selection
        function toggleBillingFrequencyFieldsets() {
            // Get the frequency and billing_date select elements
            var frequencySelect = $('#id_frequency');
            var billingDateSelect = $('#id_billing_date');
            console.log('Frequency Select:', frequencySelect);
            if (frequencySelect.length === 0 || billingDateSelect.length === 0) {
                return;
            }
            console.log('Billing Date Select:', billingDateSelect);
            var frequency = frequencySelect.val();
            var billingDate = billingDateSelect.val();
            console.log('Selected Frequency:', frequency);
            console.log('Selected Billing Date:', billingDate);
            // Find the fieldsets to toggle
            var specificDateFieldset = $('.form-row').filter(function() {
                return $(this).prev('h2').text().includes('Configuración de Fecha Específica') ||
                       $(this).find('label[for*="specific_day"]').length > 0;
            }).closest('.collapse');
            
            var weekdayFieldset = $('.form-row').filter(function() {
                return $(this).prev('h2').text().includes('Configuración de Día de la Semana') ||
                       $(this).find('label[for*="weekday"]').length > 0 ||
                       $(this).find('label[for*="occurrence"]').length > 0;
            }).closest('.collapse');
            
            // Alternative way to find fieldsets if the above doesn't work
            if (specificDateFieldset.length === 0) {
                specificDateFieldset = $('div.collapse').filter(function() {
                    return $(this).find('label[for*="specific_day"]').length > 0;
                });
            }
            
            if (weekdayFieldset.length === 0) {
                weekdayFieldset = $('div.collapse').filter(function() {
                    return $(this).find('label[for*="weekday"]').length > 0 ||
                           $(this).find('label[for*="occurrence"]').length > 0;
                });
            }
            
            // Logic: Hide both fieldsets if frequency is 'monthly' AND billing_date is 'last_day' or 'first_day'
            var shouldHide = frequency === 'monthly' && (billingDate === 'last_day' || billingDate === 'first_day');
            
            if(frequency === 'biweekly'){
                console.log('Biweekly selected - showing specific date drop box');
                $('.field-billing_date').hide(300);
                // reset the billingDate dropdown to first option, which is emtpy or non value
                billingDateSelect.val('');

                shouldHide = true;
            }

            if(frequency === 'monthly'){
                console.log('Monthly selected - showing billing date drop box');
                $('.field-billing_date').show(300);
            }

            if (shouldHide) {
                specificDateFieldset.slideUp(300);
                weekdayFieldset.slideUp(300);
            } else {
                // Show fieldsets based on billing_date selection
                if (billingDate === 'specific_date') {
                    specificDateFieldset.slideDown(300);
                    weekdayFieldset.slideUp(300);
                } else if (billingDate === 'weekday_occurrence') {
                    specificDateFieldset.slideUp(300);
                    weekdayFieldset.slideDown(300);
                } else {
                    // For other billing_date options, hide both
                    specificDateFieldset.slideUp(300);
                    weekdayFieldset.slideUp(300);
                }
            }
        }
        
        // Initial toggle on page load
        $(document).ready(function() {
            toggleBillingFrequencyFieldsets();
            console.log('Initialized billing frequency field toggle.');
            // Toggle fieldsets on frequency or billing_date change
            $('#id_frequency, #id_billing_date').on('change', function() {
                toggleBillingFrequencyFieldsets();
            });
        });
    }
    
    // Execute when Django admin is ready
    if (typeof django !== 'undefined' && django.jQuery) {
        initBillingFrequencyFieldToggle();
    } else {
        // Fallback: wait for DOM and django to be available
        document.addEventListener('DOMContentLoaded', function() {
            if (typeof django !== 'undefined' && django.jQuery) {
                initBillingFrequencyFieldToggle();
            }
        });
    }
})();
