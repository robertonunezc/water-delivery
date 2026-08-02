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

  function closeDropdowns(exceptMenu) {
    document.querySelectorAll(".pg-dropdown-menu.pg-open").forEach(function (menu) {
      if (menu === exceptMenu) return;
      menu.classList.remove("pg-open");
      var trigger = document.querySelector('[data-pg-toggle="dropdown"][aria-controls="' + menu.id + '"]');
      if (trigger) setExpanded(trigger, false);
    });
  }

  function toggleDropdown(trigger) {
    var menu = closestTarget(trigger);
    if (!menu) {
      menu = trigger.parentElement ? trigger.parentElement.querySelector(".pg-dropdown-menu") : null;
    }
    if (!menu) return;

    var willOpen = !menu.classList.contains("pg-open");
    closeDropdowns(menu);
    menu.classList.toggle("pg-open", willOpen);
    setExpanded(trigger, willOpen);
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
