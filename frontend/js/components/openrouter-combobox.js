/**
 * OpenRouter Combobox — componente accesible de búsqueda y selección.
 *
 * WAI-ARIA 1.2 combobox con input editable + listbox filtrable,
 * navegación por teclado y ratón, tema visual "Scholarly Forge".
 *
 * @module openrouter-combobox
 */

let _nextId = 0;

/**
 * Crea un combobox de búsqueda.
 *
 * @param {HTMLElement} mountEl - Contenedor donde montar el combobox (se limpia).
 * @param {Object} options
 * @param {string} options.placeholder - Texto placeholder del input
 * @param {Array<{value:string, label:string, sublabel?:string, meta?:string}>} options.items - Opciones
 * @param {(value:string, item:Object)=>void} options.onSelect - Callback al seleccionar
 * @param {string} [options.emptyText="No se encontraron resultados"]
 * @param {(item:Object)=>string} [options.getItemLabel] - Extracción de texto para búsqueda
 * @returns {{setItems, getValue, setValue, focus, destroy}}
 */
export function createCombobox(mountEl, options) {
  const id = _nextId++;
  const listboxId = `combobox-${id}-listbox`;
  const placeholder = options.placeholder || "";
  let items = options.items || [];
  const onSelect = options.onSelect || (() => {});
  const emptyText = options.emptyText || "No se encontraron resultados";
  const getItemLabel = options.getItemLabel || ((item) => item.label);

  let isOpen = false;
  let activeIndex = -1;
  let selectedValue = "";
  let isDestroyed = false;

  // --- DOM ---
  mountEl.textContent = "";

  const wrapper = document.createElement("div");
  wrapper.className = "combobox-wrapper";
  wrapper.setAttribute("aria-expanded", "false");
  wrapper.setAttribute("aria-controls", listboxId);

  const input = document.createElement("input");
  input.type = "text";
  input.className = "combobox-input form-input";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", listboxId);
  input.setAttribute("aria-activedescendant", "");
  input.placeholder = placeholder;
  input.autocomplete = "off";

  const chevron = document.createElement("span");
  chevron.className = "combobox-chevron";
  chevron.setAttribute("aria-hidden", "true");
  chevron.textContent = "▼";

  const listbox = document.createElement("ul");
  listbox.id = listboxId;
  listbox.className = "combobox-listbox";
  listbox.setAttribute("role", "listbox");
  listbox.hidden = true;

  wrapper.appendChild(input);
  wrapper.appendChild(chevron);
  wrapper.appendChild(listbox);
  mountEl.appendChild(wrapper);

  // --- Filtrado ---
  function filterItems(query) {
    if (!query.trim()) return items;
    const q = query.toLowerCase();
    return items.filter((item) => {
      const label = getItemLabel(item).toLowerCase();
      const sub = (item.sublabel || "").toLowerCase();
      return label.includes(q) || sub.includes(q);
    });
  }

  // --- Render ---
  function render() {
    if (isDestroyed) return;
    const query = input.value;
    const filtered = filterItems(query);
    const capped = filtered.length > 100;
    const visible = capped ? filtered.slice(0, 100) : filtered;

    listbox.textContent = "";

    if (visible.length === 0) {
      const noRes = document.createElement("li");
      noRes.className = "combobox-no-results";
      noRes.setAttribute("role", "option");
      noRes.setAttribute("aria-selected", "false");
      noRes.textContent = emptyText;
      listbox.appendChild(noRes);
      activeIndex = -1;
    } else {
      visible.forEach((item, i) => {
        const li = document.createElement("li");
        li.className = "combobox-option";
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", item.value === selectedValue ? "true" : "false");
        li.dataset.value = item.value;
        li.id = `combobox-${id}-opt-${i}`;

        if (item.value === selectedValue) {
          li.classList.add("selected");
        }

        const nameSpan = document.createElement("span");
        nameSpan.className = "combobox-option-name";
        nameSpan.textContent = item.label;

        const idSpan = document.createElement("span");
        idSpan.className = "combobox-option-id";
        idSpan.textContent = item.sublabel || "";

        const metaSpan = document.createElement("span");
        metaSpan.className = "combobox-option-meta";
        metaSpan.textContent = item.meta || "";

        li.appendChild(nameSpan);
        li.appendChild(idSpan);
        li.appendChild(metaSpan);

        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          commitOption(i, item);
        });

        li.addEventListener("mouseenter", () => {
          setActive(i);
        });

        listbox.appendChild(li);
      });

      if (capped) {
        const capHint = document.createElement("li");
        capHint.className = "combobox-cap-hint";
        capHint.textContent = "Más de 100 resultados — refina la búsqueda";
        listbox.appendChild(capHint);
      }

      // Reset active if filtered list changes
      if (activeIndex >= visible.length) activeIndex = -1;
    }

    if (isOpen) {
      listbox.hidden = false;
    }
  }

  // --- Active management ---
  function setActive(index) {
    if (isDestroyed) return;
    const opts = listbox.querySelectorAll(".combobox-option");
    opts.forEach((el) => el.classList.remove("active"));

    if (index >= 0 && index < opts.length) {
      const el = opts[index];
      el.classList.add("active");
      el.scrollIntoView({ block: "nearest" });
      input.setAttribute("aria-activedescendant", el.id);
      activeIndex = index;
    } else {
      input.setAttribute("aria-activedescendant", "");
      activeIndex = -1;
    }
  }

  function commitOption(index, overrideItem) {
    if (isDestroyed) return;
    const filtered = filterItems(input.value);
    const visible = filtered.length > 100 ? filtered.slice(0, 100) : filtered;
    const item = overrideItem || visible[index];
    if (!item) return;

    selectedValue = item.value;
    input.value = item.label;
    close();
    onSelect(item.value, item);
    render();
  }

  // --- Open / close ---
  function open() {
    if (isDestroyed || isOpen) return;
    isOpen = true;
    listbox.hidden = false;
    wrapper.classList.add("open");
    wrapper.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-expanded", "true");
    render();
    if (activeIndex < 0) setActive(0);
  }

  function close() {
    if (isDestroyed || !isOpen) return;
    isOpen = false;
    listbox.hidden = true;
    wrapper.classList.remove("open");
    wrapper.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-activedescendant", "");
    activeIndex = -1;
  }

  function toggle() {
    if (isOpen) close();
    else open();
  }

  // --- Event handlers ---
  function onInput(e) {
    selectedValue = "";
    render();
    if (!isOpen) open();
    activeIndex = -1;
    if (filterItems(input.value).length > 0) setActive(0);
  }

  function onKeyDown(e) {
    const filtered = filterItems(input.value);
    const visible = filtered.length > 100 ? filtered.slice(0, 100) : filtered;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!isOpen) open();
        else {
          const next = activeIndex < visible.length - 1 ? activeIndex + 1 : 0;
          setActive(next);
        }
        break;

      case "ArrowUp":
        e.preventDefault();
        if (!isOpen) open();
        else {
          const prev = activeIndex > 0 ? activeIndex - 1 : visible.length - 1;
          setActive(prev);
        }
        break;

      case "Enter":
        e.preventDefault();
        if (isOpen && activeIndex >= 0 && activeIndex < visible.length) {
          commitOption(activeIndex);
        } else if (isOpen) {
          close();
        }
        break;

      case "Escape":
        e.preventDefault();
        close();
        break;

      case "Tab":
        close();
        break;

      case "Home":
        e.preventDefault();
        if (!isOpen) open();
        else setActive(0);
        break;

      case "End":
        e.preventDefault();
        if (!isOpen) open();
        else setActive(visible.length - 1);
        break;

      default:
        break;
    }
  }

  function onDocumentClick(e) {
    if (isDestroyed) return;
    if (!wrapper.contains(e.target)) {
      close();
    }
  }

  function onInputClick() {
    toggle();
  }

  // --- Attach listeners ---
  input.addEventListener("input", onInput);
  input.addEventListener("keydown", onKeyDown);
  input.addEventListener("click", onInputClick);
  document.addEventListener("click", onDocumentClick);

  // --- Public API ---
  const api = {
    setItems(newItems) {
      items = newItems;
      selectedValue = "";
      render();
    },

    getValue() {
      return input.value;
    },

    setValue(val) {
      input.value = val;
      selectedValue = "";
      render();
    },

    focus() {
      input.focus();
    },

    destroy() {
      if (isDestroyed) return;
      isDestroyed = true;
      input.removeEventListener("input", onInput);
      input.removeEventListener("keydown", onKeyDown);
      input.removeEventListener("click", onInputClick);
      document.removeEventListener("click", onDocumentClick);
      mountEl.textContent = "";
    },
  };

  return api;
}