

document.addEventListener("DOMContentLoaded", function () {

    console.log("SmartShop AI JavaScript loaded successfully.");

    

    const toggleButtons =
        document.querySelectorAll(".password-toggle");

    toggleButtons.forEach(function (button) {

        button.addEventListener("click", function () {

            const inputId =
                button.getAttribute("data-target");

            const passwordInput =
                document.getElementById(inputId);

            if (!passwordInput) {
                return;
            }

            if (passwordInput.type === "password") {
                passwordInput.type = "text";
                button.innerHTML = "🙈 Hide Password";
            } else {
                passwordInput.type = "password";
                button.innerHTML = "👁️ Show Password";
            }

        });

    });

    
    const alerts =
        document.querySelectorAll(".alert");

    alerts.forEach(function (alert) {

        setTimeout(function () {

            if (
                typeof bootstrap !== "undefined"
            ) {

                const bootstrapAlert =
                    bootstrap.Alert.getOrCreateInstance(alert);

                bootstrapAlert.close();

            }

        }, 5000);

    });

    

    const buyForms =
        document.querySelectorAll(
            'form[action*="/buy/"]'
        );

    buyForms.forEach(function (form) {

        form.addEventListener("submit", function (event) {

            const confirmed = confirm(
                "Are you sure you want to add this product to your shopping history?"
            );

            if (!confirmed) {
                event.preventDefault();
            }

        });

    });

    

    const favouriteForms =
        document.querySelectorAll(
            'form[action*="/favourite/"]'
        );

    favouriteForms.forEach(function (form) {

        form.addEventListener("submit", function () {

            console.log(
                "Favourite button clicked."
            );

        });

    });

});