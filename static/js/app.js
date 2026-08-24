// FastFest Application JS

document.addEventListener('DOMContentLoaded', () => {
    // Auto dismiss flash alerts after 6 seconds
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            try {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            } catch (e) {}
        }, 6000);
    });

    // Toggle free event pricing input in event creation
    const isFreeCheckbox = document.getElementById('is_free');
    const feeInputGroup = document.getElementById('fee_input_group');
    const feeInput = document.getElementById('registration_fee');

    if (isFreeCheckbox && feeInputGroup) {
        const toggleFee = () => {
            if (isFreeCheckbox.checked) {
                feeInputGroup.style.display = 'none';
                if (feeInput) feeInput.value = '0.0';
            } else {
                feeInputGroup.style.display = 'block';
            }
        };
        isFreeCheckbox.addEventListener('change', toggleFee);
        toggleFee();
    }
});
