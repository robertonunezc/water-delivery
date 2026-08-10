(function () {
  "use strict";

  function closestTarget(trigger) {
    var selector = trigger.getAttribute("data-pg-target") || trigger.getAttribute("href");
    if (!selector || selector === "#") return null;
    try {
      return document.querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function setExpanded(trigger, isExpanded) {
    trigger.setAttribute("aria-expanded", isExpanded ? "true" : "false");
  }

  var dropdownState = new WeakMap();
  var dropdownGap = 6;
  var dropdownViewportPadding = 8;

  function getDropdownMenu(trigger) {
    var controlledId = trigger.getAttribute("aria-controls");
    if (controlledId) {
      var controlledMenu = document.getElementById(controlledId);
      if (controlledMenu && controlledMenu.classList.contains("pg-dropdown-menu")) {
        return controlledMenu;
      }
    }

    var target = closestTarget(trigger);
    if (target && target.classList.contains("pg-dropdown-menu")) {
      return target;
    }

    return trigger.parentElement ? trigger.parentElement.querySelector(".pg-dropdown-menu") : null;
  }

  function getDropdownTrigger(menu) {
    var state = dropdownState.get(menu);
    if (state && state.trigger) return state.trigger;
    if (!menu.id) return null;
    return document.querySelector('[data-pg-toggle="dropdown"][aria-controls="' + menu.id + '"]');
  }

  function clearDropdownPosition(menu) {
    menu.style.removeProperty("left");
    menu.style.removeProperty("top");
    menu.style.removeProperty("right");
    menu.style.removeProperty("bottom");
    menu.style.removeProperty("min-width");
  }

  function restoreDropdownMenu(menu) {
    var state = dropdownState.get(menu);
    menu.classList.remove("pg-dropdown-menu-fixed");
    clearDropdownPosition(menu);

    if (!state || !state.parent || menu.parentElement === state.parent) return;
    var nextSibling = state.nextSibling && state.nextSibling.parentElement === state.parent ? state.nextSibling : null;
    state.parent.insertBefore(menu, nextSibling);
  }

  function hasClippingAncestor(element) {
    var node = element.parentElement;
    while (node && node !== document.body) {
      var styles = window.getComputedStyle ? window.getComputedStyle(node) : null;
      if (styles) {
        var overflow = [styles.overflow, styles.overflowX, styles.overflowY].join(" ");
        if (/(auto|scroll|hidden|clip)/.test(overflow)) return true;
      }
      node = node.parentElement;
    }
    return false;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function portDropdownMenu(trigger, menu) {
    var state = dropdownState.get(menu) || {};
    if (menu.parentElement !== document.body) {
      state.parent = menu.parentElement;
      state.nextSibling = menu.nextSibling;
    }
    state.trigger = trigger;
    dropdownState.set(menu, state);

    menu.classList.add("pg-dropdown-menu-fixed");
    document.body.appendChild(menu);
  }

  function positionDropdownMenu(trigger, menu) {
    if (!menu.classList.contains("pg-dropdown-menu-fixed")) return;

    var rect = trigger.getBoundingClientRect();
    var viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    var viewportHeight = document.documentElement.clientHeight || window.innerHeight;
    var menuWidth = menu.offsetWidth;
    var menuHeight = menu.offsetHeight;
    var maxLeft = Math.max(dropdownViewportPadding, viewportWidth - menuWidth - dropdownViewportPadding);
    var left = menu.classList.contains("pg-dropdown-menu-end")
      ? Math.max(rect.left, rect.right - menuWidth)
      : rect.left;
    left = clamp(left, dropdownViewportPadding, maxLeft);

    var belowTop = rect.bottom + dropdownGap;
    var aboveTop = rect.top - menuHeight - dropdownGap;
    var maxTop = Math.max(dropdownViewportPadding, viewportHeight - menuHeight - dropdownViewportPadding);
    var top = belowTop;
    if (belowTop + menuHeight > viewportHeight - dropdownViewportPadding && aboveTop >= dropdownViewportPadding) {
      top = aboveTop;
    } else {
      top = clamp(belowTop, dropdownViewportPadding, maxTop);
    }

    menu.style.setProperty("left", Math.round(left) + "px");
    menu.style.setProperty("top", Math.round(top) + "px");
    menu.style.setProperty("min-width", Math.ceil(rect.width) + "px");
  }

  function positionOpenDropdowns() {
    document.querySelectorAll(".pg-dropdown-menu.pg-open.pg-dropdown-menu-fixed").forEach(function (menu) {
      var trigger = getDropdownTrigger(menu);
      if (trigger) positionDropdownMenu(trigger, menu);
    });
  }

  function openDropdownMenu(trigger, menu) {
    menu.classList.add("pg-open");
    setExpanded(trigger, true);

    if (hasClippingAncestor(trigger)) {
      portDropdownMenu(trigger, menu);
      positionDropdownMenu(trigger, menu);
    } else {
      restoreDropdownMenu(menu);
    }
  }

  function closeDropdownMenu(menu) {
    menu.classList.remove("pg-open");
    var trigger = getDropdownTrigger(menu);
    if (trigger) setExpanded(trigger, false);
    restoreDropdownMenu(menu);
  }

  function closeDropdowns(exceptMenu) {
    document.querySelectorAll(".pg-dropdown-menu.pg-open").forEach(function (menu) {
      if (menu === exceptMenu) return;
      closeDropdownMenu(menu);
    });
  }

  function toggleDropdown(trigger) {
    var menu = getDropdownMenu(trigger);
    if (!menu) return;

    var willOpen = !menu.classList.contains("pg-open");
    closeDropdowns(menu);
    if (willOpen) {
      openDropdownMenu(trigger, menu);
    } else {
      closeDropdownMenu(menu);
    }
  }

  function toggleCollapse(trigger) {
    var target = closestTarget(trigger);
    if (!target) return;

    var willOpen = !target.classList.contains("pg-show");
    target.classList.toggle("pg-show", willOpen);
    setExpanded(trigger, willOpen);
  }

  function activateTab(trigger) {
    var target = closestTarget(trigger);
    if (!target) return;

    var tabList = trigger.closest('[role="tablist"]') || trigger.closest(".pg-tabs");
    var scope = tabList ? tabList.parentElement : document;
    if (tabList) {
      tabList.querySelectorAll('[data-pg-toggle="tab"]').forEach(function (tab) {
        tab.classList.remove("pg-active");
        tab.setAttribute("aria-selected", "false");
      });
    }

    scope.querySelectorAll(".pg-tab-pane").forEach(function (pane) {
      pane.classList.remove("pg-show", "pg-active");
    });

    trigger.classList.add("pg-active");
    trigger.setAttribute("aria-selected", "true");
    target.classList.add("pg-show", "pg-active");
  }

  function openModal(trigger) {
    var target = closestTarget(trigger);
    if (!target) return;

    target.classList.add("pg-open", "pg-show");
    target.removeAttribute("aria-hidden");
    document.body.classList.add("pg-modal-open");

    var closeButton = target.querySelector("[data-pg-dismiss='modal'], .pg-modal-close");
    if (closeButton) closeButton.focus({ preventScroll: true });
  }

  function closeModal(modal) {
    if (!modal) return;
    modal.classList.remove("pg-open", "pg-show");
    modal.setAttribute("aria-hidden", "true");
    if (!document.querySelector(".pg-modal.pg-open")) {
      document.body.classList.remove("pg-modal-open");
    }
  }

  function dismissAlert(trigger) {
    var alert = trigger.closest(".pg-alert");
    if (alert) alert.remove();
  }

  function handleClick(event) {
    var trigger = event.target.closest("[data-pg-toggle], [data-pg-dismiss]");
    if (!trigger) {
      if (!event.target.closest(".pg-dropdown")) closeDropdowns(null);
      return;
    }

    var dismiss = trigger.getAttribute("data-pg-dismiss");
    if (dismiss === "alert") {
      event.preventDefault();
      dismissAlert(trigger);
      return;
    }

    if (dismiss === "modal") {
      event.preventDefault();
      closeModal(trigger.closest(".pg-modal"));
      return;
    }

    var toggle = trigger.getAttribute("data-pg-toggle");
    if (toggle === "dropdown") {
      event.preventDefault();
      toggleDropdown(trigger);
      return;
    }
    if (toggle === "collapse") {
      event.preventDefault();
      toggleCollapse(trigger);
      return;
    }
    if (toggle === "tab") {
      event.preventDefault();
      activateTab(trigger);
      return;
    }
    if (toggle === "modal") {
      event.preventDefault();
      openModal(trigger);
      return;
    }
    if (toggle === "nav") {
      event.preventDefault();
      toggleCollapse(trigger);
    }
  }

  function handleKeydown(event) {
    if (event.key !== "Escape") return;
    closeDropdowns(null);
    closeModal(document.querySelector(".pg-modal.pg-open"));
  }

  function initializeTabs() {
    document.querySelectorAll('[data-pg-toggle="tab"]').forEach(function (tab) {
      var target = closestTarget(tab);
      if (!target) return;
      if (tab.classList.contains("pg-active") || target.classList.contains("pg-show")) {
        tab.setAttribute("aria-selected", "true");
        target.classList.add("pg-show", "pg-active");
      } else {
        tab.setAttribute("aria-selected", "false");
      }
    });
  }

  function initializeDismissButtons() {
    document.querySelectorAll(".pg-alert-close:not([aria-label])").forEach(function (button) {
      button.setAttribute("aria-label", "Cerrar");
    });
    document.querySelectorAll(".pg-modal-close:not([aria-label])").forEach(function (button) {
      button.setAttribute("aria-label", "Cerrar");
    });
  }

  function initializeDropdowns() {
    document.querySelectorAll('[data-pg-toggle="dropdown"]').forEach(function (trigger, index) {
      var menu = trigger.parentElement ? trigger.parentElement.querySelector(".pg-dropdown-menu") : null;
      if (!menu) return;
      if (!menu.id) menu.id = "pg-dropdown-menu-" + index;
      trigger.setAttribute("aria-controls", menu.id);
      setExpanded(trigger, menu.classList.contains("pg-open"));
    });
  }

  function ready() {
    initializeTabs();
    initializeDropdowns();
    initializeDismissButtons();
    document.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKeydown);
    document.addEventListener("scroll", positionOpenDropdowns, true);
    window.addEventListener("resize", positionOpenDropdowns);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }

  window.pgDesignSystem = {
    closeModal: closeModal,
    openModal: openModal,
    activateTab: activateTab,
    toggleCollapse: toggleCollapse
  };
})();
