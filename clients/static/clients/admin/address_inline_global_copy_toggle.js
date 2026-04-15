(function () {
    'use strict';

    class AddressInlineGlobalCopyToggle {
        constructor() {
            this.$ = django.jQuery;
            this.fieldName = 'copy_address_for_all_inlines';
            this.containerSelectors = [
                '#addresses-group',
                '.inline-group#addresses-group',
                '.inline-group[id*="addresses"]',
            ];
        }

        getAddressInlineContainer() {
            for (const selector of this.containerSelectors) {
                const container = this.$(selector).first();
                if (container.length) {
                    return container;
                }
            }

            const firstAddressRow = this.$('[id^="addresses-"]').first();
            if (firstAddressRow.length) {
                return firstAddressRow.closest('.inline-group, .module');
            }

            return this.$();
        }

        buildToggleMarkup() {
            return this.$(`
                <div class="form-row field-${this.fieldName}" style="margin-bottom: 12px;">
                    <div>
                        <label style="display: flex; align-items: center; gap: 8px; font-weight: 600;">
                            <input type="checkbox" name="${this.fieldName}" id="id_${this.fieldName}">
                                Copiar esta dirección como direccion fiscal 
                        </label>
                      
                    </div>
                </div>
            `);
        }

        injectToggle() {
            if (this.$(`#id_${this.fieldName}`).length) {
                return;
            }

            const container = this.getAddressInlineContainer();
            if (!container.length) {
                return;
            }

            const body = container.find('h2, .inline-group, .tab-content, .module').first();
            const toggle = this.buildToggleMarkup();

            if (body.length) {
                toggle.insertBefore(body);
            } else {
                container.prepend(toggle);
            }
        }

        init() {
            const self = this;
            this.$(document).ready(function () {
                self.injectToggle();
            });
        }
    }

    function initialize() {
        if (typeof django !== 'undefined' && django.jQuery) {
            const manager = new AddressInlineGlobalCopyToggle();
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
