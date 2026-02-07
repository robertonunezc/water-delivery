(function() {
    'use strict';
    
    /**
     * Class to manage billing inline visibility based on checkbox states
     */
    class BillingInlineManager {
        constructor() {
            this.$ = django.jQuery;
            this.requiresBillingCheckbox = null;
            this.toggleBillingFormCheckbox = null;
            this.billingDataInline = null;
            this.billingFrequencyInline = null;
            this.billingDataInfo = null;
        }

        /**
         * Initialize DOM element references
         */
        initializeElements() {
            this.requiresBillingCheckbox = this.$('#id_requires_billing');
            this.toggleBillingFormCheckbox = this.$('#toggle_billing_form');
            this.billingDataInline = this.$('#billing_data-group');
            this.billingFrequencyInline = this.$('#billing_frecuency-group');
            this.billingDataInfo = this.$('.tab-billing-inheritance');
        }

        /**
         * Toggle billing inlines based on requires_billing checkbox
         */
        toggleBillingInlines() {
            if (this.requiresBillingCheckbox.length === 0) {
                return;
            }
            
            const isChecked = this.requiresBillingCheckbox.is(':checked');
            
            console.log('Toggling billing inlines. requires_billing:', isChecked);
            
            if (isChecked) {
                this.billingFrequencyInline.slideDown(300);
                this.billingDataInfo.slideDown(300);
            } else {
                this.billingDataInline.slideUp(300);
                this.billingFrequencyInline.slideUp(300);
                this.billingDataInfo.slideUp(300);
            }
        }

        /**
         * Toggle billing data inline based on toggle_billing_form checkbox
         */
        toggleBillingDataForm() {
            if (this.toggleBillingFormCheckbox.length === 0) {
                return;
            }
            
            const isChecked = this.toggleBillingFormCheckbox.is(':checked');
            
            console.log('Toggling billing data form. toggle_billing_form:', isChecked);
            
            if (isChecked) {
                this.billingDataInline.slideDown(300);
            } else {
                this.billingDataInline.slideUp(300);
            }
        }

        /**
         * Attach event listeners to checkboxes
         */
        attachEventListeners() {
            if (this.requiresBillingCheckbox.length > 0) {
                this.requiresBillingCheckbox.on('change', () => {
                    this.toggleBillingInlines();
                });
            }

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
                this.toggleBillingInlines();
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
