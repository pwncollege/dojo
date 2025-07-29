$(document).ready(function() {
    const requiredText = "I have read the ground rules and commit to not publish writeups on the internet.";
    
    function normalizeText(text) {
        return text.toLowerCase().replace(/[^a-z]/g, '');
    }
    
    const normalizedRequired = normalizeText(requiredText);
    
    $('#groundRulesInput').on('input', function() {
        const inputValue = $(this).val().trim();
        const normalizedInput = normalizeText(inputValue);
        const isValid = normalizedInput === normalizedRequired;
        
        if (isValid) {
            $(this).removeClass('is-invalid').addClass('is-valid');
            $('#acceptGroundRules').prop('disabled', false);
        } else {
            $(this).removeClass('is-valid');
            if (inputValue.length > 0) {
                $(this).addClass('is-invalid');
            }
            $('#acceptGroundRules').prop('disabled', true);
        }
    });
    
    $('#acceptGroundRules').click(function() {
        const inputValue = $('#groundRulesInput').val().trim();
        const normalizedInput = normalizeText(inputValue);
        if (normalizedInput === normalizedRequired) {
            localStorage.setItem('groundRulesAccepted', 'true');
            
            $('#groundRulesModal').modal('hide');
            
            $('#groundRulesInput').val('').removeClass('is-valid is-invalid');
            $('#acceptGroundRules').prop('disabled', true);
            
            if (window.pendingChallengeEvent && typeof startChallenge === 'function') {
                const event = window.pendingChallengeEvent;
                delete window.pendingChallengeEvent;
                startChallenge(event);
            }
            
            if (window.pendingNavbarChallengeEvent && typeof DropdownStartChallenge === 'function') {
                const event = window.pendingNavbarChallengeEvent;
                delete window.pendingNavbarChallengeEvent;
                setTimeout(() => DropdownStartChallenge(event), 100);
            }
        }
    });
    
    $('#groundRulesModal').on('hidden.bs.modal', function() {
        $('#groundRulesInput').val('').removeClass('is-valid is-invalid');
        $('#acceptGroundRules').prop('disabled', true);
    });
});
