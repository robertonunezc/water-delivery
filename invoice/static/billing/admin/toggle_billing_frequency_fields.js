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
            if (frequencySelect.length === 0 || billingDateSelect.length === 0) {
                return;
            }

            var frequency = frequencySelect.val();
            var billingDate = billingDateSelect.val();

            var billingDateField = $('.field-billing_date');
            var specificDayField = $('.field-specific_day');
            var weekdayField = $('.field-weekday');
            var occurrenceField = $('.field-occurrence');

            billingDateField.show(300);
            specificDayField.hide(300);
            weekdayField.hide(300);
            occurrenceField.hide(300);

            if (frequency === 'weekly') {
                billingDateField.hide(300);
                billingDateSelect.val('');
                weekdayField.show(300);
                return;
            }

            if (frequency === 'when_delivery' || frequency === 'biweekly') {
                billingDateField.hide(300);
                billingDateSelect.val('');
                return;
            }

            if (frequency !== 'monthly') {
                return;
            }

            if (billingDate === 'specific_date') {
                specificDayField.show(300);
                return;
            }

            if (billingDate === 'weekday_occurrence') {
                occurrenceField.show(300);
                weekdayField.show(300);
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
