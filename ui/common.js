// Druppie Common UI Logic

/**
 * Setup global fetch interceptor for Authentication
 */
function setupAuth() {
    // Fetch interceptor to add auth token
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
        let [resource, config] = args;
        if (typeof resource === 'string' && resource.startsWith('/v1/')) {
            config = config || {};
            config.headers = config.headers || {};
            const token = localStorage.getItem('druppie_token');
            if (token) {
                config.headers['Authorization'] = 'Bearer ' + token;
            }
        }

        try {
            const response = await originalFetch(resource, config);
            if (response.status === 401) {
                // Prevent recursion: don't trigger auth failure on login/logout calls
                if (typeof resource === 'string' && (resource.includes('/iam/login') || resource.includes('/iam/logout'))) {
                    return response;
                }

                // Determine if we are in main window or popup/iframe
                if (window.opener) {
                    alert('Authentication required. Please login from the main UI.');
                    window.close();
                } else if (typeof window.onAuthFailure === 'function') {
                    window.onAuthFailure();
                } else {
                    // If we are main UI, let the specific page handle redirect or show login modal
                    console.warn("Auth required (401)");
                }
            }
            return response;
        } catch (error) {
            throw error;
        }
    };
}

/**
 * Fetch and display system version
 * Expects an element with id="app-version"
 */
async function fetchVersion() {
    try {
        const res = await fetch('/v1/version');
        const data = await res.json();
        const el = document.getElementById('app-version');
        if (el) el.textContent = `v${data.version}`;
    } catch (e) {
        console.error("Failed to fetch version", e);
    }
}

// Run Auth Setup Immediately
setupAuth();

// Initialize Icons and Version on Load
document.addEventListener('DOMContentLoaded', () => {
    fetchVersion();
    if (window.lucide) window.lucide.createIcons();
});
