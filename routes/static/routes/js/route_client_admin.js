/**
 * Route Client Admin JavaScript
 * Handles client duplicate assignment validation and confirmation
 */

(function($) {
    'use strict';

    // Cache for client assignments to avoid repeated AJAX calls
    var clientAssignmentCache = {};
    
    // Run immediately when script loads
    function runImmediately() {
        // Find error containers — works with both standard Django (.errorlist) and Unfold (.text-red-600)
        var errorSelectors = '.field-client .errorlist, td.field-client.errors, .field-client .text-red-600, .field-client .text-red-500';
        $(errorSelectors).each(function() {
            var $el = $(this);
            var $formRow = $el.closest('tr.form-row').length ? $el.closest('tr.form-row') : $el.closest('tr');
            if (!$formRow.length) $formRow = $el.closest('.form-row');
            if (!$formRow.length) return;

            $formRow.addClass('has-client-error');

            var errorText = $el.text();
            if (errorText.includes('CONFLICTO DE ASIGNACIÓN') || errorText.includes('ya está asignado')) {
                $formRow.addClass('has-duplicate-warning');
                var $confirmContainer = $formRow.find('td.field-confirm_duplicate_assignment, .field-confirm_duplicate_assignment').first();
                $confirmContainer.addClass('has-conflict');
            }
        });
    }
    
    // Run immediately
    runImmediately();

    // Initialize when document is ready
    $(document).ready(function() {
        initializeRouteClientValidation();
        
        // Check for existing validation errors and show confirmation checkbox
        checkExistingValidationErrors();
        
        // Run again in case DOM wasn't fully ready
        setTimeout(function() {
            runImmediately();
            checkExistingValidationErrors();
        }, 100);
        
        // Re-initialize when new inline forms are added
        $(document).on('formset:added', function(event, $row) {
            initializeClientValidation($row);
        });
    });
    
    function initializeRouteClientValidation() {
        // Initialize validation for existing inline forms
        $('.route-client-inline .client-select').each(function() {
            initializeClientValidation($(this).closest('.inline-related'));
        });
    }
    
    function initializeClientValidation($formRow) {
        var $clientSelect = $formRow.find('.client-select');
        var $confirmCheckbox = $formRow.find('.confirm-duplicate-checkbox');
        var $confirmContainer = $confirmCheckbox.closest('.field-confirm_duplicate_assignment');
        
        if ($clientSelect.length === 0) return;
        
        // Hide confirmation checkbox initially
        $confirmContainer.hide();
        
        // Handle client selection change
        $clientSelect.on('change', function() {
            var clientId = $(this).val();
            
            if (!clientId) {
                hideConfirmation($formRow);
                return;
            }
            
            checkClientAssignments(clientId, $formRow);
        });
        
        // Handle form submission to ensure confirmation is checked if needed
        $formRow.closest('form').on('submit', function(event) {
            var clientId = $clientSelect.val();
            var hasConflict = $formRow.hasClass('has-duplicate-warning') || $confirmContainer.hasClass('has-conflict');
            var isConfirmed = $confirmCheckbox.is(':checked');
            var checkboxVisible = $confirmCheckbox.is(':visible') && $confirmCheckbox.css('display') !== 'none';
            
            if (clientId && hasConflict && checkboxVisible && !isConfirmed) {
                event.preventDefault();
                alert('Por favor confirme la asignación duplicada marcando la casilla de confirmación.');
                $confirmCheckbox.focus();
                return false;
            }
        });
    }
    
    function checkClientAssignments(clientId, $formRow) {
        // Check cache first
        if (clientAssignmentCache[clientId]) {
            handleAssignmentCheck(clientAssignmentCache[clientId], $formRow);
            return;
        }
        
        // Get current route ID from the URL or form
        var currentRouteId = getCurrentRouteId();
        var currentAssignmentId = getCurrentAssignmentId($formRow);
        
        // Make AJAX call to check assignments
        $.ajax({
            url: '/routes/check-client-assignments/',
            method: 'GET',
            data: {
                'client_id': clientId,
                'current_route_id': currentRouteId,
                'current_assignment_id': currentAssignmentId
            },
            success: function(response) {
                clientAssignmentCache[clientId] = response;
                handleAssignmentCheck(response, $formRow);
            },
            error: function(xhr, status, error) {
                console.error('Error checking client assignments:', error);
                // Fallback to showing confirmation if AJAX fails
                showConfirmation($formRow, 'No se pudo verificar las asignaciones existentes. Proceda con precaución.');
            }
        });
    }
    
    function handleAssignmentCheck(response, $formRow) {
        if (response.has_conflicts) {
            var message = 'El cliente ya está asignado a las siguientes rutas: ' + 
                         response.existing_routes.join(', ') + 
                         '. ¿Confirma la asignación duplicada?';
            showConfirmation($formRow, message);
        } else {
            hideConfirmation($formRow);
        }
    }
    
    function showConfirmation($formRow, message) {
        var $confirmContainer = $formRow.find('.field-confirm_duplicate_assignment');
        var $confirmCheckbox = $formRow.find('.confirm-duplicate-checkbox');
        var $helpText = $confirmContainer.find('.help');
        
        // Create compact message
        var existingRoutes = message.match(/rutas: (.+)\./)?.[1] || 'otra ruta';
        var compactMessage = 'Cliente ya asignado a: ' + existingRoutes;
        
        // Update help text with compact message
        if ($helpText.length === 0) {
            $helpText = $('<div class="help compact-warning"></div>');
            $confirmContainer.append($helpText);
        }
        $helpText.html('<strong>⚠️ ' + compactMessage + '</strong>');
        
        // Position the confirmation field as an overlay
        if ($formRow.closest('.tabular').length) {
            // For tabular inline, position as overlay
            $confirmContainer.css({
                'position': 'absolute',
                'top': '100%',
                'left': '0',
                'right': '35px',
                'z-index': '100'
            });
        }
        
        // Show the container and reset checkbox
        $confirmContainer.show();
        $confirmCheckbox.prop('checked', false);
        
        // Add visual styling to indicate required attention
        $confirmContainer.addClass('duplicate-assignment-warning');
        $formRow.addClass('has-duplicate-warning');
        
        // Add tooltip with full details on the help text
        $helpText.attr('title', message.replace(/\n/g, ' '));
    }
    
    function hideConfirmation($formRow) {
        var $confirmContainer = $formRow.find('.field-confirm_duplicate_assignment');
        var $confirmCheckbox = $formRow.find('.confirm-duplicate-checkbox');
        
        $confirmContainer.hide();
        $confirmCheckbox.prop('checked', false);
        $confirmContainer.removeClass('duplicate-assignment-warning');
        $formRow.removeClass('has-duplicate-warning');
    }
    
    function getCurrentRouteId() {
        // Try to extract route ID from URL
        var match = window.location.pathname.match(/\/routes\/route\/(\d+)\//);
        if (match) {
            return match[1];
        }
        
        // Try to get from form
        var $routeIdInput = $('input[name="route_id"]');
        if ($routeIdInput.length) {
            return $routeIdInput.val();
        }
        
        return null;
    }
    
    function getCurrentAssignmentId($formRow) {
        // Get the assignment ID from the form row if editing existing
        var $idInput = $formRow.find('input[name$="-id"]');
        return $idInput.length ? $idInput.val() : null;
    }
    
    function checkExistingValidationErrors() {
        // Collect error elements — standard Django (.errorlist li) and Unfold (.text-red-600 inside td.field-client)
        var $errorItems = $('.field-client .errorlist li, td.field-client.errors .text-red-600, td.field-client.errors .text-red-500');

        $errorItems.each(function() {
            var $errorItem = $(this);
            var $formRow = $errorItem.closest('tr.form-row').length ? $errorItem.closest('tr.form-row') : $errorItem.closest('tr');
            if (!$formRow.length) $formRow = $errorItem.closest('.form-row');
            if (!$formRow.length) return;

            var errorText = $errorItem.html();

            if (errorText.includes('CONFLICTO DE ASIGNACIÓN') || errorText.includes('ya está asignado')) {
                var $confirmContainer = $formRow.find('td.field-confirm_duplicate_assignment, .field-confirm_duplicate_assignment').first();
                var $confirmCheckbox = $formRow.find('.confirm-duplicate-checkbox');

                if ($confirmContainer.length && $confirmCheckbox.length) {
                    $formRow.addClass('has-duplicate-warning');
                    $confirmContainer.addClass('has-conflict');

                    // Remove the inline display:none and make checkbox visible
                    $confirmCheckbox.removeAttr('style');
                    $confirmCheckbox.css('display', 'inline-block');
                    $confirmCheckbox.show();

                    // Show the container itself (may be hidden)
                    $confirmContainer.show();

                    // Create or update label
                    var $existingLabel = $confirmContainer.find('label');
                    if ($existingLabel.length) {
                        $existingLabel.html('').append($confirmCheckbox).append(' ✓ Confirmar duplicado');
                        $existingLabel.show();
                    } else {
                        var $newLabel = $('<label style="display: inline-block; font-size: 12px; color: #856404; font-weight: bold;"></label>');
                        $newLabel.append($confirmCheckbox).append(' ✓ Confirmar duplicado');
                        $confirmContainer.prepend($newLabel);
                    }
                }
            }
        });
    }
    
    // CSS styles are now handled by route_admin.css

})(django.jQuery);