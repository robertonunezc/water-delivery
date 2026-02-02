(function() {
    'use strict';

    function initBillingFrequencyPopup() {
        var $ = django.jQuery;

        $(document).ready(function() {
            // Handle click on the add billing frequency button
            $(document).on('click', '.add-billing-frequency-popup', function(e) {
                e.preventDefault();

                var href = $(this).attr('href');
                var popupName = 'add_billing_frequency';
                var popupWidth = 800;
                var popupHeight = 600;

                // Calculate center position
                var left = (screen.width - popupWidth) / 2;
                var top = (screen.height - popupHeight) / 2;

                // Open popup window
                var popup = window.open(
                    href + '&_popup=1',
                    popupName,
                    'width=' + popupWidth +
                    ',height=' + popupHeight +
                    ',left=' + left +
                    ',top=' + top +
                    ',scrollbars=yes,resizable=yes'
                );

                if (popup) {
                    popup.focus();
                }

                return false;
            });
        });
    }

    // Execute when Django admin is ready
    if (typeof django !== 'undefined' && django.jQuery) {
        initBillingFrequencyPopup();
    } else {
        document.addEventListener('DOMContentLoaded', function() {
            if (typeof django !== 'undefined' && django.jQuery) {
                initBillingFrequencyPopup();
            }
        });
    }
})();
