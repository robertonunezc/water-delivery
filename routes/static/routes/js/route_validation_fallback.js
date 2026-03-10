/* Inline script to show confirmation checkbox when there are validation errors */
/* Compatible with both standard Django admin (.errorlist) and Unfold (.text-red-600 / td.errors) */

function showDuplicateConfirmation(formRow, confirmContainer, confirmCheckbox) {
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
        var newLabel = document.createElement('label');
        newLabel.style.display = 'inline-block';
        newLabel.style.fontSize = '11px';
        newLabel.style.color = '#856404';
        newLabel.style.fontWeight = 'bold';
        newLabel.appendChild(confirmCheckbox);
        newLabel.appendChild(document.createTextNode(' ✓ Confirmar duplicado'));
        confirmContainer.insertBefore(newLabel, confirmContainer.firstChild);
    }

    // Show the container itself (may be hidden)
    confirmContainer.style.display = '';

    // Add visual styling to the row
    formRow.classList.add('has-duplicate-warning');
    confirmContainer.classList.add('has-conflict');
}

function revealDuplicateCheckboxes() {
    // Strategy 1: Standard Django admin — .field-client .errorlist
    document.querySelectorAll('.field-client .errorlist').forEach(function(errorList) {
        var errorText = errorList.textContent || errorList.innerText;
        if (!errorText.includes('CONFLICTO DE ASIGNACIÓN') && !errorText.includes('ya está asignado')) return;

        var formRow = errorList.closest('.form-row') || errorList.closest('tr');
        if (!formRow) return;

        var confirmCheckbox = formRow.querySelector('.confirm-duplicate-checkbox');
        var confirmContainer = formRow.querySelector('.field-confirm_duplicate_assignment') ||
                               (confirmCheckbox ? confirmCheckbox.closest('td') : null);
        if (confirmCheckbox && confirmContainer) {
            showDuplicateConfirmation(formRow, confirmContainer, confirmCheckbox);
        }
    });

    // Strategy 2: Unfold admin — td.field-client.errors with error text in .text-red-600 / .text-red-500
    document.querySelectorAll('td.field-client.errors, .field-client .text-red-600, .field-client .text-red-500').forEach(function(el) {
        var errorText = el.textContent || el.innerText;
        if (!errorText.includes('CONFLICTO DE ASIGNACIÓN') && !errorText.includes('ya está asignado')) return;

        var formRow = el.closest('tr.form-row') || el.closest('tr') || el.closest('.form-row');
        if (!formRow) return;

        var confirmCheckbox = formRow.querySelector('.confirm-duplicate-checkbox');
        var confirmContainer = formRow.querySelector('td.field-confirm_duplicate_assignment') ||
                               formRow.querySelector('.field-confirm_duplicate_assignment') ||
                               (confirmCheckbox ? confirmCheckbox.closest('td') : null);
        if (confirmCheckbox && confirmContainer) {
            showDuplicateConfirmation(formRow, confirmContainer, confirmCheckbox);
        }
    });
}

document.addEventListener('DOMContentLoaded', revealDuplicateCheckboxes);

// Also run immediately in case DOMContentLoaded already fired
revealDuplicateCheckboxes();