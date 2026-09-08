(function () {
    "use strict";

    const contenedor = document.getElementById("estado-consulta");
    if (!contenedor || contenedor.dataset.respondida === "true") return;

    const estadoUrl = contenedor.dataset.estadoUrl;
    const pendiente = document.getElementById("respuesta-pendiente");
    const recibida = document.getElementById("respuesta-recibida");
    const texto = document.getElementById("texto-respuesta");
    const estadoAutomatico = document.getElementById("estado-automatico");
    let comprobando = false;
    let temporizador = null;

    function programarComprobacion() {
        window.clearTimeout(temporizador);
        temporizador = window.setTimeout(comprobarRespuesta, 5000);
    }

    async function comprobarRespuesta() {
        if (comprobando) {
            programarComprobacion();
            return;
        }

        comprobando = true;

        try {
            const response = await fetch(estadoUrl, {
                method: "GET",
                cache: "no-store",
                credentials: "same-origin",
                headers: { "Accept": "application/json" }
            });

            if (!response.ok) throw new Error("No se pudo comprobar la respuesta");

            const datos = await response.json();

            if (datos.respondida) {
                texto.textContent = datos.respuesta;
                pendiente.hidden = true;
                recibida.hidden = false;
                contenedor.dataset.respondida = "true";
                recibida.scrollIntoView({ behavior: "smooth", block: "start" });
                return;
            }

            estadoAutomatico.textContent =
                "Seguimos esperando la respuesta. Esta página se actualiza automáticamente.";
        } catch (error) {
            estadoAutomatico.textContent =
                "No hemos podido comprobarlo ahora. Lo intentaremos de nuevo automáticamente.";
        } finally {
            comprobando = false;
        }

        programarComprobacion();
    }

    document.addEventListener("visibilitychange", function () {
        if (!document.hidden && contenedor.dataset.respondida !== "true") {
            comprobarRespuesta();
        }
    });

    programarComprobacion();
}());
