(function () {
    'use strict';

    /**
     * Fields that are eligible for copying between address rows.
     * Excludes: type, client, id, DELETE, and management fields.
     */
    const COPYABLE_FIELDS = [
        'street',
        'exterior_number',
        'interior_number',
        'locality',
        'municipality',
        'state',
        'zip_code',
        'country',
        'reference',
    ];

    /**
     * Manages the "misma dirección que la anterior" checkbox behavior
     * inside the Address inline of the Client admin.
     *
     * Visibility rules:
     *   - Client requires_billing must be true.
     *   - Current row type is "billing" and a non-deleted "shipping" row exists, OR
     *   - Current row type is "shipping" and a non-deleted "billing" row exists.
     *
     * When checked, copies address fields from the first matching opposite-type row.
     */
    class AddressInlineCopyManager {
        constructor() {
            this.$ = django.jQuery;
            this.inlinePrefix = 'addresses';
        }

        // ---------------------------------------------------------------
        // DOM helpers
        // ---------------------------------------------------------------

        /**
         * Return the jQuery-wrapped requires_billing checkbox.
         */
        getRequiresBillingCheckbox() {
            return this.$('#id_requires_billing');
        }

        /**
         * Return true when the client requires billing.
         */
        isRequiresBilling() {
            const cb = this.getRequiresBillingCheckbox();
            return cb.length > 0 && cb.is(':checked');
        }

        /**
         * Return all visible inline rows (stacked or tabular).
         */
        getInlineRows() {
            return this.$(`[id^="${this.inlinePrefix}-"]`).filter(function () {
                return /^addresses-\d+$/.test(this.id);
            });
        }

        /**
         * Extract the numeric index from an inline row element.
         */
        getRowIndex(row) {
            const match = this.$(row).attr('id').match(/addresses-(\d+)/);
            return match ? match[1] : null;
        }

        /**
         * Build a field selector for a given row index and field name.
         */
        fieldSelector(index, fieldName) {
            return `#id_${this.inlinePrefix}-${index}-${fieldName}`;
        }

        /**
         * Return the type value of a given row.
         */
        getRowType(index) {
            return this.$(this.fieldSelector(index, 'type')).val();
        }

        /**
         * Return true when a given row is marked for deletion.
         */
        isRowDeleted(index) {
            const delCheckbox = this.$(this.fieldSelector(index, 'DELETE'));
            return delCheckbox.length > 0 && delCheckbox.is(':checked');
        }

        /**
         * Return the checkbox field for same_as_previous on a given row.
         */
        getSameAsPreviousCheckbox(index) {
            return this.$(this.fieldSelector(index, 'same_as_previous'));
        }

        /**
         * Return the wrapper element that contains the same_as_previous field
         * so we can show/hide it.
         */
        getSameAsPreviousWrapper(index) {
            const cb = this.getSameAsPreviousCheckbox(index);
            // Unfold / stacked inline: walk up to the form-row / field wrapper
            const wrapper = cb.closest('.form-row, .field-same_as_previous, div[class*="mb-"]');
            return wrapper.length ? wrapper : cb.parent();
        }

        // ---------------------------------------------------------------
        // Opposite-type resolution
        // ---------------------------------------------------------------

        /**
         * Return the opposite address type for a given type string.
         */
        oppositeType(type) {
            if (type === 'billing') return 'shipping';
            if (type === 'shipping') return 'billing';
            return null;
        }

        /**
         * Find the first non-deleted row whose type matches `targetType`.
         * Returns its index string or null.
         */
        findSourceRow(targetType) {
            const rows = this.getInlineRows();
            for (let i = 0; i < rows.length; i++) {
                const idx = this.getRowIndex(rows[i]);
                if (idx === null) continue;
                if (this.isRowDeleted(idx)) continue;
                if (this.getRowType(idx) === targetType) return idx;
            }
            return null;
        }

        // ---------------------------------------------------------------
        // Visibility logic
        // ---------------------------------------------------------------

        /**
         * Evaluate and set visibility for the same_as_previous checkbox
         * on a single row identified by its index.
         */
        evaluateRow(index) {
            const wrapper = this.getSameAsPreviousWrapper(index);
            const rowType = this.getRowType(index);
            const opposite = this.oppositeType(rowType);

            const shouldShow =
                this.isRequiresBilling() &&
                opposite !== null &&
                this.findSourceRow(opposite) !== null;

            if (shouldShow) {
                wrapper.show();
            } else {
                wrapper.hide();
                // Uncheck if hiding
                this.getSameAsPreviousCheckbox(index).prop('checked', false);
            }
        }

        /**
         * Re-evaluate all visible rows.
         */
        evaluateAllRows() {
            const self = this;
            this.getInlineRows().each(function () {
                const idx = self.getRowIndex(this);
                if (idx !== null) {
                    self.evaluateRow(idx);
                }
            });
        }

        // ---------------------------------------------------------------
        // Copy logic
        // ---------------------------------------------------------------

        /**
         * Copy COPYABLE_FIELDS from sourceIndex row into targetIndex row.
         */
        copyFields(sourceIndex, targetIndex) {
            for (const field of COPYABLE_FIELDS) {
                const sourceVal = this.$(this.fieldSelector(sourceIndex, field)).val();
                if (sourceVal !== undefined) {
                    this.$(this.fieldSelector(targetIndex, field)).val(sourceVal);
                }
            }
        }

        /**
         * Handle same_as_previous checkbox change.
         */
        handleCheckboxChange(index) {
            const cb = this.getSameAsPreviousCheckbox(index);
            if (!cb.is(':checked')) return;

            const rowType = this.getRowType(index);
            const opposite = this.oppositeType(rowType);
            if (!opposite) return;

            const sourceIndex = this.findSourceRow(opposite);
            if (sourceIndex === null) return;

            this.copyFields(sourceIndex, index);
        }

        // ---------------------------------------------------------------
        // Event binding
        // ---------------------------------------------------------------

        /**
         * Bind events on a single row.
         */
        bindRowEvents(index) {
            const self = this;

            // Type select change -> re-evaluate all rows
            this.$(this.fieldSelector(index, 'type')).on('change', function () {
                self.evaluateAllRows();
            });

            // Delete checkbox toggle -> re-evaluate all rows
            this.$(this.fieldSelector(index, 'DELETE')).on('change', function () {
                self.evaluateAllRows();
            });

            // same_as_previous change -> copy & re-evaluate
            this.getSameAsPreviousCheckbox(index).on('change', function () {
                self.handleCheckboxChange(index);
                self.evaluateAllRows();
            });
        }

        /**
         * Bind events for all currently rendered rows and global triggers.
         */
        bindAllEvents() {
            const self = this;

            // Per-row events
            this.getInlineRows().each(function () {
                const idx = self.getRowIndex(this);
                if (idx !== null) {
                    self.bindRowEvents(idx);
                }
            });

            // requires_billing toggle -> re-evaluate
            this.getRequiresBillingCheckbox().on('change', function () {
                self.evaluateAllRows();
            });

            // formset:added -> bind new row and re-evaluate
            this.$(document).on('formset:added', function (_event, $row) {
                // Small delay to allow Django to render the new row
                setTimeout(function () {
                    self.getInlineRows().each(function () {
                        const idx = self.getRowIndex(this);
                        if (idx !== null) {
                            self.bindRowEvents(idx);
                        }
                    });
                    self.evaluateAllRows();
                }, 100);
            });
        }

        // ---------------------------------------------------------------
        // Initialization
        // ---------------------------------------------------------------

        init() {
            const self = this;
            this.$(document).ready(function () {
                self.evaluateAllRows();
                self.bindAllEvents();
            });
        }
    }

    // Bootstrap
    function initialize() {
        if (typeof django !== 'undefined' && django.jQuery) {
            const manager = new AddressInlineCopyManager();
            manager.init();
        }
    }

    if (typeof django !== 'undefined' && django.jQuery) {
        initialize();
    } else {
        document.addEventListener('DOMContentLoaded', function () {
            initialize();
        });
    }
})();
