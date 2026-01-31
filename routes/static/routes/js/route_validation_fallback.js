/* Inline script to show confirmation checkbox when there are validation errors */
document.addEventListener('DOMContentLoaded', function() {
    // Find all rows with client validation errors
    var errorRows = document.querySelectorAll('.field-client .errorlist');
    
    errorRows.forEach(function(errorList) {
        var formRow = errorList.closest('.form-row');
        var errorText = errorList.textContent || errorList.innerText;
        
        // Check if this is a duplicate assignment error
        if (errorText.includes('CONFLICTO DE ASIGNACIÓN') || errorText.includes('ya está asignado')) {
            var confirmCheckbox = formRow.querySelector('.confirm-duplicate-checkbox');
            var confirmContainer = formRow.querySelector('.field-confirm_duplicate_assignment');
            
            if (confirmCheckbox && confirmContainer) {
                // Show the checkbox
                confirmCheckbox.style.display = 'inline-block';
                confirmCheckbox.style.marginRight = '5px';
                
                // Add or update label
                var label = confirmContainer.querySelector('label');
                if (label) {
                    label.style.display = 'inline-block';
                    label.style.fontSize = '11px';
                    label.style.color = '#856404';
                    label.style.fontWeight = 'bold';
                    label.innerHTML = '';
                    label.appendChild(confirmCheckbox);
                    label.appendChild(document.createTextNode(' ✓ Confirmar duplicado'));
                } else {
                    // Create new label
                    var newLabel = document.createElement('label');
                    newLabel.style.display = 'inline-block';
                    newLabel.style.fontSize = '11px';
                    newLabel.style.color = '#856404';
                    newLabel.style.fontWeight = 'bold';
                    newLabel.appendChild(confirmCheckbox);
                    newLabel.appendChild(document.createTextNode(' ✓ Confirmar duplicado'));
                    confirmContainer.insertBefore(newLabel, confirmContainer.firstChild);
                }
                
                // Add visual styling to the row
                formRow.classList.add('has-duplicate-warning');
                confirmContainer.classList.add('has-conflict');
            }
        }
    });
});

// Also run immediately in case DOMContentLoaded already fired
(function() {
    var errorRows = document.querySelectorAll('.field-client .errorlist');
    
    errorRows.forEach(function(errorList) {
        var formRow = errorList.closest('.form-row');
        var errorText = errorList.textContent || errorList.innerText;
        
        if (errorText.includes('CONFLICTO DE ASIGNACIÓN') || errorText.includes('ya está asignado')) {
            var confirmCheckbox = formRow.querySelector('.confirm-duplicate-checkbox');
            var confirmContainer = formRow.querySelector('.field-confirm_duplicate_assignment');
            
            if (confirmCheckbox && confirmContainer) {
                confirmCheckbox.style.display = 'inline-block';
                confirmCheckbox.style.marginRight = '5px';
                
                var label = confirmContainer.querySelector('label');
                if (label) {
                    label.style.display = 'inline-block';
                    label.style.fontSize = '11px';
                    label.style.color = '#856404';
                    label.style.fontWeight = 'bold';
                    label.innerHTML = '';
                    label.appendChild(confirmCheckbox);
                    label.appendChild(document.createTextNode(' ✓ Confirmar duplicado'));
                } else {
                    var newLabel = document.createElement('label');
                    newLabel.style.display = 'inline-block';
                    newLabel.style.fontSize = '11px';
                    newLabel.style.color = '#856404';
                    newLabel.style.fontWeight = 'bold';
                    newLabel.appendChild(confirmCheckbox);
                    newLabel.appendChild(document.createTextNode(' ✓ Confirmar duplicado'));
                    confirmContainer.insertBefore(newLabel, confirmContainer.firstChild);
                }
                
                formRow.classList.add('has-duplicate-warning');
                confirmContainer.classList.add('has-conflict');
            }
        }
    });
})();