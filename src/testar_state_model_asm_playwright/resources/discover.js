(options) => {
    // Build exact main-document selectors without adding attributes to the application.
    function selectorFor(element) {
        const parts = [];
        while (element) {
            let index = 1;
            let previous = element.previousElementSibling;
            while (previous) {
                if (previous.localName === element.localName) {
                    index += 1;
                }
                previous = previous.previousElementSibling;
            }
            parts.unshift(CSS.escape(element.localName) + ":nth-of-type(" + index + ")");
            element = element.parentElement;
        }
        return parts.join(" > ");
    }

    function signatureFor(element) {
        return JSON.stringify([element.localName, element.id, element.getAttribute("name"),
            element.getAttribute("type"), element.getAttribute("href"),
            element.getAttribute("aria-label"), element.textContent]);
    }

    // Validate configured selectors even when the document contains no controls.
    for (const selector of [...options.inputSelectors, ...options.excluded]) {
        document.querySelector(selector);
    }
    const actions = [];
    const selector = 'a[href], button, input, textarea, [role="button"], [role="link"]';
    for (const element of document.querySelectorAll(selector)) {
        if (actions.length >= options.limit) {
            break;
        }
        const style = getComputedStyle(element);
        if (!element.getClientRects().length || style.visibility === "hidden"
                || style.visibility === "collapse" || element.matches(":disabled")
                || element.closest('[inert], [aria-disabled="true"]')
                || options.excluded.some(selector => element.closest(selector))) {
            continue;
        }
        // Fills are offered only when the caller provided a value for this field.
        const inputSelector = options.inputSelectors.find(selector => element.matches(selector));
        const textInput = element instanceof HTMLTextAreaElement
            || (element instanceof HTMLInputElement
                && ["text", "email", "password", "search", "tel", "url", "number"].includes(element.type));
        const name = (element.getAttribute("aria-label") || element.getAttribute("name")
            || element.id || element.textContent.trim() || element.localName).slice(0, 200);
        if (textInput) {
            if (inputSelector && !element.readOnly) {
                actions.push({ type: "fill", name: "Fill " + name,
                    selector: selectorFor(element), inputSelector, signature: signatureFor(element) });
            }
            continue;
        }
        const clickable = element.matches('a[href], button, [role="button"], [role="link"]')
            || (element instanceof HTMLInputElement
                && ["button", "submit", "reset", "checkbox", "radio", "image"].includes(element.type));
        if (!clickable) {
            continue;
        }
        if (element instanceof HTMLAnchorElement) {
            const address = new URL(element.href, document.URL);
            if (!["http:", "https:"].includes(address.protocol) || element.hasAttribute("download")
                    || (element.target && element.target !== "_self")
                    || (options.sameOrigin && address.origin !== location.origin)) {
                continue;
            }
        }
        actions.push({ type: "click", name: "Click " + name, selector: selectorFor(element), signature: signatureFor(element) });
    }
    return actions;
}
