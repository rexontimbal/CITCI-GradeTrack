// In-app QR scanner for the "Join a class" modal (Scan QR tab) -- lets a
// student join by pointing their device camera at the instructor's QR
// without leaving the page or needing their phone's own camera app. Decodes
// frames with the vendored jsQR library (no network/CDN call per project
// convention); on a recognized code it navigates to the same join_with_code
// confirmation page a scanned QR from the native camera app lands on.
document.addEventListener("alpine:init", () => {
    Alpine.data("qrScanner", (joinUrlTemplate) => ({
        tab: "code",
        error: "",
        joinUrlTemplate,
        _stream: null,
        _raf: null,

        start() {
            this.error = "";
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                this.error = "Camera not supported on this device/browser. Use Enter code instead.";
                return;
            }
            navigator.mediaDevices
                .getUserMedia({ video: { facingMode: "environment" } })
                .then((stream) => {
                    this._stream = stream;
                    const video = this.$refs.video;
                    video.srcObject = stream;
                    video.play();
                    this._raf = requestAnimationFrame(() => this._tick());
                })
                .catch(() => {
                    this.error = "Camera access was denied. Allow camera permission, or use Enter code instead.";
                });
        },

        _tick() {
            if (!this._stream) return;
            const video = this.$refs.video;
            if (video.readyState === video.HAVE_ENOUGH_DATA && video.videoWidth) {
                const canvas = this.$refs.canvas;
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext("2d");
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const result = window.jsQR && window.jsQR(imageData.data, imageData.width, imageData.height);
                if (result && result.data) {
                    this._onDecoded(result.data);
                    return;
                }
            }
            this._raf = requestAnimationFrame(() => this._tick());
        },

        _extractCode(text) {
            const trimmed = text.trim();
            const segments = trimmed.split("/").filter(Boolean);
            const candidate = segments.length ? segments[segments.length - 1] : trimmed;
            const clean = candidate.toUpperCase();
            return /^[A-Z0-9]{4,12}$/.test(clean) ? clean : null;
        },

        _onDecoded(text) {
            const code = this._extractCode(text);
            if (!code) {
                this._raf = requestAnimationFrame(() => this._tick());
                return;
            }
            this.stop();
            window.location.href = this.joinUrlTemplate.replace("CODE", code);
        },

        stop() {
            if (this._raf) cancelAnimationFrame(this._raf);
            this._raf = null;
            if (this._stream) {
                this._stream.getTracks().forEach((track) => track.stop());
                this._stream = null;
            }
        },
    }));
});
