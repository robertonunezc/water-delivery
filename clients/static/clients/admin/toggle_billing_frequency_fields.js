(function() {
    'use strict';
    
    /**
     * BillingFrequencyFieldToggler class
     * Manages visibility and behavior of billing frequency fields in Django admin
     */
    class BillingFrequencyFieldToggler {
        constructor() {
            this.$ = null;
            this.observer = null;
            this.retryTimeouts = [];
            this.selectors = {
                frequency: 'select[name$="-frequency"], #id_invoiceschedule-frequency, #id_frequency',
                billingDate: 'select[name$="-billing_date"], #id_invoiceschedule-billing_date, #id_billing_date',
                specificDate: '.field-specific_day',
                weekday: '.field-weekday',
                occurrence: '.field-occurrence',
                billingDateField: '.field-billing_date'
            };
            this.inlineFieldSelector = '.inline-related, .inline-group, .module';
            this.eventNamespace = 'billingFrequency';
            this.logPrefix = '[BillingFrequency]';
        }

        /**
         * Initialize the toggler
         */
        init() {
            if (typeof django === 'undefined' || !django.jQuery) {
                this.log('Django or jQuery not available');
                return;
            }

            this.$ = django.jQuery;
            this.log('Script initialized');

            this.$(document).ready(() => {
                this.log('Document ready');
                this.setupEventDelegation();
                this.attachEventListeners();
                this.setupDjangoFormsetListeners();
                this.setupDOMObserver();
                this.scheduleRetries();
            });
        }

        /**
         * Log messages with consistent prefix
         */
        log(message, ...args) {
            console.log(`${this.logPrefix} ${message}`, ...args);
        }

        /**
         * Get form elements
         */
        getFormElements() {
            const frequencySelect = this.getActiveSelect('frequency');
            const billingDateSelect = this.getActiveSelect('billing_date');
            const inlineContainer = this.getInlineContainer(frequencySelect, billingDateSelect);

            return {
                frequencySelect,
                billingDateSelect,
                billingDateField: this.getFieldContainer(this.selectors.billingDateField, inlineContainer),
                containerSpecificDate: this.getFieldContainer(this.selectors.specificDate, inlineContainer),
                containerWeekday: this.getFieldContainer(this.selectors.weekday, inlineContainer),
                containerOccurrence: this.getFieldContainer(this.selectors.occurrence, inlineContainer)
            };
        }

        getActiveSelect(fieldName) {
            let selector = this.selectors.billingDate;
            if (fieldName === 'frequency') {
                selector = this.selectors.frequency;
            }
            const fields = this.$(selector).filter((_, element) => {
                const $element = this.$(element);
                return !$element.closest('.empty-form').length;
            });

            return fields.first();
        }

        getInlineContainer(frequencySelect, billingDateSelect) {
            const sourceElement = frequencySelect.length ? frequencySelect : billingDateSelect;
            if (!sourceElement.length) {
                return this.$();
            }

            return sourceElement.closest(this.inlineFieldSelector).first();
        }

        getFieldContainer(selector, inlineContainer) {
            if (inlineContainer && inlineContainer.length) {
                const scoped = inlineContainer.find(selector).first();
                if (scoped.length) {
                    return scoped;
                }
            }

            return this.$(selector).not('.empty-form *').first();
        }

        /**
         * Check if form elements are available
         */
        areElementsAvailable(elements) {
            return elements.frequencySelect.length > 0 && elements.billingDateSelect.length > 0;
        }

        /**
         * Toggle billing frequency fieldsets based on frequency and billing_date selection
         */
        toggleFieldsets() {
            this.log('toggleFieldsets called');

            const elements = this.getFormElements();
            
            this.log('Frequency select found:', elements.frequencySelect.length);
            this.log('Billing date select found:', elements.billingDateSelect.length);

            if (!this.areElementsAvailable(elements)) {
                this.log('Elements not found, skipping...');
                return;
            }

            const frequency = elements.frequencySelect.val();
            const billingDate = elements.billingDateSelect.val();

            this.log('Current values - Frequency:', frequency, 'Billing Date:', billingDate);

            // Toggle billing_date field visibility based on frequency
            this.toggleBillingDateFieldVisibility(frequency, elements);

            // Hide specific date and weekday occurrence fieldsets initially
            elements.containerSpecificDate.hide();
            elements.containerWeekday.hide();
            elements.containerOccurrence.hide();

            this.handleFrequencyLogic(frequency, billingDate, elements);
        }

        /**
         * Toggle billing_date field visibility based on frequency value
         */
        toggleBillingDateFieldVisibility(frequency, elements) {
            const billingDateFieldContainer = elements.billingDateField;
            
            if (frequency === 'when_delivery' || frequency === 'weekly') {
                this.log('Frequency hides billing_date field');
                billingDateFieldContainer.slideUp(300);
            } else {
                this.log('Frequency is not "when_delivery" - showing billing_date field');
                billingDateFieldContainer.slideDown(300);
            }
        }

        /**
         * Handle frequency-specific logic
         */
        handleFrequencyLogic(frequency, billingDate, elements) {
            let shouldHide = frequency === 'monthly' && 
                           (billingDate === 'last_day' || billingDate === 'first_day');

            if (frequency === 'when_delivery') {
                shouldHide = true;
            }

            if (frequency === 'weekly') {
                this.handleWeeklyFrequency(elements);
                shouldHide = true;
            }

            if (frequency === 'biweekly') {
                this.handleBiweeklyFrequency(elements);
                shouldHide = true;
            }

            if (frequency === 'monthly') {
                this.handleMonthlyFrequency(elements);
            }

            this.applyFieldVisibility(shouldHide, frequency, billingDate, elements);
        }

        /**
         * Handle weekly frequency selection
         */
        handleWeeklyFrequency(elements) {
            this.log('Weekly selected - showing weekday field only');
            elements.billingDateField.hide(300);
            elements.billingDateSelect.val('');
            elements.containerSpecificDate.slideUp(300);
            elements.containerOccurrence.slideUp(300);
            elements.containerWeekday.slideDown(300);
        }

        /**
         * Handle biweekly frequency selection
         */
        handleBiweeklyFrequency(elements) {
            this.log('Biweekly selected - hiding billing date field');
            elements.billingDateField.hide(300);
            // Reset the billingDate dropdown to first option, which is empty or non value
            elements.billingDateSelect.val('');
        }

        /**
         * Handle monthly frequency selection
         */
        handleMonthlyFrequency(elements) {
            this.log('Monthly selected - showing billing date field');
            elements.billingDateField.show(300);
        }

        /**
         * Apply field visibility based on billing date selection
         */
        applyFieldVisibility(shouldHide, frequency, billingDate, elements) {
            const hideAll = () => {
                elements.containerSpecificDate.slideUp(300);
                elements.containerWeekday.slideUp(300);
                elements.containerOccurrence.slideUp(300);
            };

            if (shouldHide) {
                if (frequency === 'weekly') {
                    elements.containerWeekday.slideDown(300);
                    return;
                }
                hideAll();
                return;
            }

            // Show fieldsets based on billing_date selection
            if (billingDate === 'specific_date') {
                elements.containerSpecificDate.slideDown(300);
                elements.containerWeekday.slideUp(300);
                elements.containerOccurrence.slideUp(300);
                return;
            }

            if (billingDate === 'weekday_occurrence' && frequency === 'monthly') {
                elements.containerSpecificDate.slideUp(300);
                elements.containerOccurrence.slideDown(300);
                elements.containerWeekday.slideDown(300);
                return;
            }

            // For weekly, when_delivery, and any other billing_date, hide all dependent fields
            hideAll();
        }

        /**
         * Attach event listeners to form elements
         */
        attachEventListeners() {
            this.log('Attempting to attach event listeners...');

            const elements = this.getFormElements();

            if (!this.areElementsAvailable(elements)) {
                this.log('Elements not found yet, will retry...');
                return;
            }

            this.log('Elements found! Attaching listeners...');

            // Remove any existing listeners to avoid duplicates
            elements.frequencySelect.off(`change.${this.eventNamespace}`);
            elements.billingDateSelect.off(`change.${this.eventNamespace}`);

            // Attach new listeners with namespace
            elements.frequencySelect.on(`change.${this.eventNamespace}`, (e) => {
                this.log('Frequency changed to:', this.$(e.currentTarget).val());
                this.toggleFieldsets();
            });

            elements.billingDateSelect.on(`change.${this.eventNamespace}`, (e) => {
                this.log('Billing date changed to:', this.$(e.currentTarget).val());
                this.toggleFieldsets();
            });

            this.log('Event listeners attached successfully');

            // Run initial toggle
            this.toggleFieldsets();
        }

        /**
         * Setup event delegation for dynamic forms
         */
        setupEventDelegation() {
            const delegatedSelectors = 'select[name$="-frequency"], select[name$="-billing_date"], #id_frequency, #id_billing_date, #id_invoiceschedule-frequency, #id_invoiceschedule-billing_date';
            this.$(document).on('change', 
                delegatedSelectors,
                (e) => {
                    this.log('Change detected via delegation on:', e.target.id);
                    this.toggleFieldsets();
                }
            );
        }

        /**
         * Setup Django admin inline formset event listeners
         */
        setupDjangoFormsetListeners() {
            // Watch for Django admin inline formset events
            this.$(document).on('formset:added', (event, $row, formsetName) => {
                this.log('Formset added:', formsetName);
                if (formsetName && (formsetName.includes('invoiceschedule') || formsetName.includes('billing_frecuency'))) {
                    setTimeout(() => this.attachEventListeners(), 100);
                }
            });

            // Watch for tab/fieldset visibility changes
            this.$(document).on('click', '.tab, .collapse-toggle, .inline-group h2', () => {
                this.log('Tab/collapse clicked, retrying attachment...');
                setTimeout(() => this.attachEventListeners(), 200);
            });
        }

        /**
         * Setup MutationObserver to watch for DOM changes
         */
        setupDOMObserver() {
            this.observer = new MutationObserver((mutations) => {
                mutations.forEach((mutation) => {
                    if (mutation.addedNodes.length > 0) {
                        const frequencySelect = this.getActiveSelect('frequency');
                        if (frequencySelect.length > 0 && !frequencySelect.data('listeners-attached')) {
                            this.log('Elements detected via MutationObserver');
                            frequencySelect.data('listeners-attached', true);
                            this.attachEventListeners();
                        }
                    }
                });
            });

            // Start observing the document body for changes
            this.observer.observe(document.body, {
                childList: true,
                subtree: true
            });
        }

        /**
         * Schedule retry attempts to attach listeners
         */
        scheduleRetries() {
            // Try after delays in case inline is initially hidden
            this.retryTimeouts.push(setTimeout(() => this.attachEventListeners(), 500));
            this.retryTimeouts.push(setTimeout(() => this.attachEventListeners(), 1000));
        }

        /**
         * Cleanup method to remove observers and timeouts
         */
        destroy() {
            if (this.observer) {
                this.observer.disconnect();
            }

            this.retryTimeouts.forEach(timeout => clearTimeout(timeout));
            this.retryTimeouts = [];

            if (this.$) {
                this.$(document).off(`.${this.eventNamespace}`);
            }

            this.log('Destroyed');
        }
    }

    // Initialize when Django admin is ready
    if (typeof django !== 'undefined' && django.jQuery) {
        const toggler = new BillingFrequencyFieldToggler();
        toggler.init();
        
        // Expose to window for debugging purposes
        window.billingFrequencyToggler = toggler;
    } else {
        // Fallback: wait for DOM and django to be available
        document.addEventListener('DOMContentLoaded', function() {
            if (typeof django !== 'undefined' && django.jQuery) {
                const toggler = new BillingFrequencyFieldToggler();
                toggler.init();
                window.billingFrequencyToggler = toggler;
            }
        });
    }
})();
