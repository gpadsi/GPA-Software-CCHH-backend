(function () {
    "use strict";

    var STORAGE_KEY = "ch_sidebar_scroll_top";
    var sidebar = document.querySelector("#jazzy-sidebar .sidebar-wrapper");
    if (!sidebar) {
        return;
    }

    try {
        var saved = sessionStorage.getItem(STORAGE_KEY);
        if (saved !== null) {
            sidebar.scrollTop = parseInt(saved, 10) || 0;
        }
    } catch (error) {
        // sessionStorage puede no estar disponible (modo privado, etc.) — sin esto
        // el menú simplemente vuelve a su comportamiento normal, no rompe nada.
    }

    sidebar.addEventListener("scroll", function () {
        try {
            sessionStorage.setItem(STORAGE_KEY, sidebar.scrollTop);
        } catch (error) {
            // ver comentario de arriba
        }
    }, { passive: true });
})();
