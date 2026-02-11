(function() {
    'use strict';

    class ClientAdminUpdater {
        constructor() {
            this.clientId = this.extractClientId();
            this.init();
        }

        extractClientId() {
            const match = window.location.pathname.match(/\/clients\/client\/(\d+)\/change\//);
            if (!match) {
                console.warn('Could not extract client ID from URL');
                return null;
            }
            return match[1];
        }

        getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === name + '=') {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }

        updateClient(data) {
            if (!this.clientId) {
                return Promise.reject(new Error('Client ID not available'));
            }

            const url = `/clients/${this.clientId}/update/`;
            return fetch(url, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken'),
                },
                body: JSON.stringify(data),
            }).then(response => {
                if (!response.ok) {
                    return response.json().then(err => Promise.reject(err));
                }
                return response.json();
            });
        }

        showNotification(message, type = 'info') {
            const messagesContainer = document.querySelector('.messagelist, .messages');

            if (messagesContainer) {
                const messageItem = document.createElement('li');
                messageItem.className = type;
                messageItem.textContent = message;
                messagesContainer.appendChild(messageItem);
                setTimeout(() => messageItem.remove(), 5000);
            } else {
                alert(message);
            }
        }

        bindCheckbox(selector, payloadBuilder) {
            const checkbox = document.querySelector(selector);
            if (!checkbox) {
                console.warn(`${selector} checkbox not found`);
                return;
            }

            checkbox.addEventListener('change', e => {
                const isChecked = e.target.checked;
                const originalValue = !isChecked;
                checkbox.disabled = true;

                this.updateClient(payloadBuilder(isChecked))
                    .then(response => {
                        if (response.success) {
                            this.showNotification(
                                response.message || 'Cliente actualizado exitosamente',
                                'success'
                            );
                            window.location.reload();
                        } else {
                            checkbox.checked = originalValue;
                            this.showNotification(
                                response.error || 'Error al actualizar cliente',
                                'error'
                            );
                        }
                    })
                    .catch(error => {
                        checkbox.checked = originalValue;
                        const errorMessage = error.error || error.message || 'Error al actualizar cliente';
                        this.showNotification(errorMessage, 'error');
                        console.error('Error updating client:', error);
                    })
                    .finally(() => {
                        checkbox.disabled = false;
                    });
            });
        }

        initHandlers() {
            this.bindCheckbox('#id_requires_billing', isChecked => ({ requires_billing: isChecked }));
            this.bindCheckbox('#id_billing_override_enabled', isChecked => ({ billing_override_enabled: isChecked }));
        }

        init() {
            if (!this.clientId) {
                return;
            }

            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => this.initHandlers());
            } else {
                this.initHandlers();
            }
        }
    }

    const updater = new ClientAdminUpdater();

    window.clientUpdateUtils = {
        updateClient: data => updater.updateClient(data),
        showNotification: (message, type) => updater.showNotification(message, type),
    };
})();
