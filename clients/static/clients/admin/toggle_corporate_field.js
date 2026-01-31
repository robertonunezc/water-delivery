(function($) {
    'use strict';
    
    $(document).ready(function() {
        const typeField = $('#id_type');
        const corporateFieldRow = $('.field-corporate');
        
        function toggleCorporateField() {
            const selectedType = typeField.val();
            
            if (selectedType === 'corporate') {
                // Hide the corporate field when type is 'corporate'
                // since a corporate client cannot have another corporate as parent
                corporateFieldRow.hide();
            } else {
                // Show the corporate field for other types (e.g., 'branch')
                corporateFieldRow.show();
            }
        }
        
        // Initial check on page load
        if (typeField.length > 0) {
            toggleCorporateField();
            
            // Listen for changes to the type field
            typeField.on('change', function() {
                toggleCorporateField();
            });
        }
    });
})(django.jQuery);
