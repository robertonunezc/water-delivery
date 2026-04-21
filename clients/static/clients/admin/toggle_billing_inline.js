(function() {
    'use strict';
    
    /**
     * Class to manage billing inline visibility based on checkbox states
     * Note: Fieldset visibility is now handled server-side via get_fieldsets()
     * This script only manages inline visibility (billing data and frequency inlines)
     */
    class BillingInlineManager {
        constructor() {
            this.$ = django.jQuery;
            this.toggleBillingFormCheckbox = null;
            this.billingDataInline = null;
            this.billingFrequencyInline = null;
        }

        /**
         * Initialize DOM element references
         */
        initializeElements() {
            this.toggleBillingFormCheckbox = this.$('#id_billing_override_enabled');
            this.billingDataInline = this.$('#invoice_data-group');
            this.billingFrequencyInline = this.$('#billing_frecuency-group');
        }

        /**
         * Toggle billing data inline based on billing_override_enabled checkbox
         */
        toggleBillingDataForm() {
            if (this.toggleBillingFormCheckbox.length === 0) {
                return;
            }
            
            const isChecked = this.toggleBillingFormCheckbox.is(':checked');
            
            console.log('Toggling billing data form. billing_override_enabled:', isChecked);
            
            // Use CSS display property to completely hide/show elements without leaving blank space
            if (isChecked) {
                this.billingDataInline.css('display', 'block');
            } else {
                this.billingDataInline.css('display', 'none');
            }
        }

        /**
         * Attach event listeners to checkboxes
         */
        attachEventListeners() {
            if (this.toggleBillingFormCheckbox.length > 0) {
                this.toggleBillingFormCheckbox.on('change', () => {
                    this.toggleBillingDataForm();
                });
            }
        }

        /**
         * Initialize the manager - set up elements, initial state, and event listeners
         */
        init() {
            this.$(document).ready(() => {
                this.initializeElements();
                this.toggleBillingDataForm();
                this.attachEventListeners();
            });
        }
    }

    /**
     * Initialize the billing inline manager when Django admin is ready
     */
    function initializeBillingManager() {
        if (typeof django !== 'undefined' && django.jQuery) {
            const manager = new BillingInlineManager();
            manager.init();
        }
    }
    
    // Execute when Django admin is ready
    if (typeof django !== 'undefined' && django.jQuery) {
        initializeBillingManager();
    } else {
        // Fallback: wait for DOM and django to be available
        document.addEventListener('DOMContentLoaded', function() {
            initializeBillingManager();
        });
    }
})();
