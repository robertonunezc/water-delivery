(function() {
    'use strict';
    
    /**
     * Update client via AJAX PATCH request
     * @param {number} clientId - The client ID
     * @param {object} data - The data to update
     * @returns {Promise} - Promise that resolves with the response
     */
    function updateClient(clientId, data) {
        console.log('Updating client with ID:', clientId, 'Data:', data);
        const url = `/clients/${clientId}/update/`;
        
        return fetch(url, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify(data),
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => Promise.reject(err));
            }
            return response.json();
        });
    }
    
    /**
     * Get CSRF token from cookies
     * @param {string} name - Cookie name
     * @returns {string|null} - Cookie value or null
     */
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    /**
     * Show notification message
     * @param {string} message - Message to display
     * @param {string} type - Message type (success, error, warning, info)
     */
    function showNotification(message, type = 'info') {
        // Try to use Django messages framework
        const messagesContainer = document.querySelector('.messagelist, .messages');
        
        if (messagesContainer) {
            const messageDiv = document.createElement('li');
            messageDiv.className = type;
            messageDiv.textContent = message;
            messagesContainer.appendChild(messageDiv);
            
            // Auto-remove after 5 seconds
            setTimeout(() => {
                messageDiv.remove();
            }, 5000);
        } else {
            // Fallback to alert if messages container not found
            alert(message);
        }
    }
    
    /**
     * Initialize requires_billing checkbox handler
     */
    function initRequiresBillingHandler() {
        console.log('Initializing requires_billing checkbox handler');
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setupHandler);
        } else {
            setupHandler();
        }
        
        function setupHandler() {
            // Find the requires_billing checkbox
            const requiresBillingCheckbox = document.querySelector('#id_requires_billing');
            
            if (!requiresBillingCheckbox) {
                console.warn('requires_billing checkbox not found');
                return;
            }
            
            // Get client ID from URL (assuming admin change form URL pattern)
            const urlMatch = window.location.pathname.match(/\/clients\/client\/(\d+)\/change\//);
            if (!urlMatch) {
                console.warn('Could not extract client ID from URL');
                return;
            }
            
            const clientId = urlMatch[1];
            
            // Add change event listener
            requiresBillingCheckbox.addEventListener('change', function(e) {
                const isChecked = e.target.checked;
                const originalValue = !isChecked; // Store original value for rollback
                
                // Disable checkbox during update
                requiresBillingCheckbox.disabled = true;
                
                // Update client
                updateClient(clientId, { requires_billing: isChecked })
                    .then(response => {
                        if (response.success) {
                            showNotification(
                                response.message || 'Cliente actualizado exitosamente',
                                'success'
                            );
                            window.location.reload();
                        } else {
                            // Rollback on failure
                            requiresBillingCheckbox.checked = originalValue;
                            showNotification(
                                response.error || 'Error al actualizar cliente',
                                'error'
                            );
                        }
                    })
                    .catch(error => {
                        // Rollback on error
                        requiresBillingCheckbox.checked = originalValue;
                        const errorMessage = error.error || error.message || 'Error al actualizar cliente';
                        showNotification(errorMessage, 'error');
                        console.error('Error updating client:', error);
                    })
                    .finally(() => {
                        // Re-enable checkbox
                        requiresBillingCheckbox.disabled = false;
                    });
            });
        }
    }
    
    // Initialize when script loads
    initRequiresBillingHandler();
    
    // Export for potential external use
    window.clientUpdateUtils = {
        updateClient: updateClient,
        showNotification: showNotification,
    };
    
})();
