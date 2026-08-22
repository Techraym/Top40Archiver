(() => {
  "use strict";

  const storageKey = "top40language";
  const languages = ["nl", "en", "de", "fr"];

  const translations = {
    en: {
      "Een lokaal muziekarchief van de Nederlandse Top 40 en Tipparade.": "A local music archive of the Dutch Top 40 and Tipparade.",
      "Lijsten controleren": "Check charts",
      "Mislukte downloads opnieuw proberen": "Retry failed downloads",
      "Laatste Top 40": "Latest Top 40",
      "Laatste Tipparade": "Latest Tipparade",
      "Nummers in database": "Tracks in database",
      "In muziekarchief": "In music archive",
      "Te verwerken": "To process",
      "Aandacht nodig": "Needs attention",
      "Actuele editie": "Current edition",
      "Unieke artiest-titelcombinaties": "Unique artist-title combinations",
      "Albumhoezen": "Cover art",
      "Coverarchief aanvullen": "Complete cover archive",
      "Actief": "Active",
      "Hoezen gevonden": "Covers found",
      "Nummers gecontroleerd": "Tracks checked",
      "Nog te controleren": "Still to check",
      "Controle voltooid": "Completed",
      "Archiefopbouw": "Archive build",
      "Historisch archief opbouwen": "Build historical archive",
      "Gepauzeerd": "Paused",
      "Totaal": "Total",
      "Volgende historische edities": "Next historical editions",
      "Start of hervat": "Start or resume",
      "Eén batch uitvoeren": "Run one batch",
      "Pauzeren": "Pause",
      "Opslag & koppelingen": "Storage & connections",
      "USB-C schrijfbaar": "USB-C writable",
      "Spotify-controle niet ingesteld": "Spotify check not configured",
      "Windows-netwerkschijf": "Windows network share",
      "Laatste editie": "Latest edition",
      "Bekijk bron": "View source",
      "Artiest": "Artist",
      "Titel": "Title",
      "Status": "Status",
      "NIEUW": "NEW",
      "In wachtrij": "Queued",
      "Gedownload": "Downloaded",
      "Downloads": "Downloads",
      "Wachtrij": "Queue",
      "Nu bezig": "Active now",
      "Actieve downloads": "Active downloads",
      "Zoeken": "Search",
      "Downloaden": "Downloading",
      "Valideren": "Validating",
      "Verwerken": "Processing",
      "Logboek": "Activity log",
      "Laatste activiteit": "Latest activity",
      "Mislukt": "Failed",
      "Mislukte downloads": "Failed downloads",
      "Geen mislukte downloads.": "No failed downloads.",
      "AI-herstel bekijken": "View AI recovery",
      "Technische details tonen": "Show technical details",
      "Opnieuw zoeken": "Search again",
      "Niet online beschikbaar": "Not available online",
      "Muziekarchief": "Music archive",
      "Onlangs opgeslagen": "Recently saved",
      "Archief zoeken": "Search archive",
      "Vind een artiest of titel": "Find an artist or title",
      "Bijvoorbeeld artiest of titel": "For example artist or title",
      "Archief doorzoeken": "Search the archive",
      "Zoek in het volledige muziekarchief op artiest of titel.": "Search the complete music archive by artist or title.",
      "Lokale database op de NUC": "Local database on the NUC",
      "Zoekresultaten": "Search results",
      "Geen resultaten gevonden.": "No results found.",
      "Hitlijsten": "Charts",
      "Muzieklijsten beheren": "Manage music charts",
      "Welke hitlijst wil je toevoegen?": "Which chart do you want to add?",
      "Analyseren met Qwen": "Analyse with Qwen",
      "Geconfigureerde hitlijsten": "Configured charts",
      "Nederlandse Top 40": "Dutch Top 40",
      "Actueel en historisch": "Current and historical",
      "Beheerinstellingen": "Management settings",
      "Technische instellingen voor Top40Archiver.": "Technical settings for Top40Archiver.",
      "Lokale configuratie op de NUC": "Local configuration on the NUC",
      "Downloadmap": "Download folder",
      "Pogingen": "Attempts",
      "Instellingen opslaan": "Save settings",
      "Bestaande MP3's opnieuw ordenen": "Reorganise existing MP3s",
      "MP3's ordenen": "Organise MP3s"
    },

    de: {
      "Een lokaal muziekarchief van de Nederlandse Top 40 en Tipparade.": "Ein lokales Musikarchiv der niederländischen Top 40 und Tipparade.",
      "Lijsten controleren": "Charts prüfen",
      "Mislukte downloads opnieuw proberen": "Fehlgeschlagene Downloads erneut versuchen",
      "Laatste Top 40": "Aktuelle Top 40",
      "Laatste Tipparade": "Aktuelle Tipparade",
      "Nummers in database": "Titel in der Datenbank",
      "In muziekarchief": "Im Musikarchiv",
      "Te verwerken": "Zu verarbeiten",
      "Aandacht nodig": "Aufmerksamkeit nötig",
      "Actuele editie": "Aktuelle Ausgabe",
      "Albumhoezen": "Coverbilder",
      "Coverarchief aanvullen": "Coverarchiv vervollständigen",
      "Actief": "Aktiv",
      "Hoezen gevonden": "Cover gefunden",
      "Nummers gecontroleerd": "Titel geprüft",
      "Nog te controleren": "Noch zu prüfen",
      "Controle voltooid": "Abgeschlossen",
      "Archiefopbouw": "Archivaufbau",
      "Historisch archief opbouwen": "Historisches Archiv aufbauen",
      "Gepauzeerd": "Pausiert",
      "Totaal": "Gesamt",
      "Start of hervat": "Starten oder fortsetzen",
      "Eén batch uitvoeren": "Einen Batch ausführen",
      "Pauzeren": "Pausieren",
      "Opslag & koppelingen": "Speicher & Verbindungen",
      "Laatste editie": "Aktuelle Ausgabe",
      "Bekijk bron": "Quelle ansehen",
      "Artiest": "Künstler",
      "Titel": "Titel",
      "Status": "Status",
      "NIEUW": "NEU",
      "In wachtrij": "Warteschlange",
      "Gedownload": "Heruntergeladen",
      "Wachtrij": "Warteschlange",
      "Nu bezig": "Jetzt aktiv",
      "Actieve downloads": "Aktive Downloads",
      "Zoeken": "Suchen",
      "Downloaden": "Herunterladen",
      "Logboek": "Protokoll",
      "Laatste activiteit": "Letzte Aktivität",
      "Mislukt": "Fehlgeschlagen",
      "Mislukte downloads": "Fehlgeschlagene Downloads",
      "Muziekarchief": "Musikarchiv",
      "Onlangs opgeslagen": "Kürzlich gespeichert",
      "Archief zoeken": "Archiv durchsuchen",
      "Vind een artiest of titel": "Künstler oder Titel finden",
      "Archief doorzoeken": "Archiv durchsuchen",
      "Hitlijsten": "Charts",
      "Muzieklijsten beheren": "Musikcharts verwalten",
      "Welke hitlijst wil je toevoegen?": "Welche Chartliste möchtest du hinzufügen?",
      "Analyseren met Qwen": "Mit Qwen analysieren",
      "Geconfigureerde hitlijsten": "Konfigurierte Charts",
      "Beheerinstellingen": "Verwaltungseinstellungen",
      "Downloadmap": "Downloadordner",
      "Instellingen opslaan": "Einstellungen speichern"
    },

    fr: {
      "Een lokaal muziekarchief van de Nederlandse Top 40 en Tipparade.": "Une archive musicale locale du Top 40 néerlandais et de la Tipparade.",
      "Lijsten controleren": "Vérifier les classements",
      "Mislukte downloads opnieuw proberen": "Réessayer les téléchargements échoués",
      "Laatste Top 40": "Dernier Top 40",
      "Laatste Tipparade": "Dernière Tipparade",
      "Nummers in database": "Titres dans la base",
      "In muziekarchief": "Dans l'archive musicale",
      "Te verwerken": "À traiter",
      "Aandacht nodig": "Attention requise",
      "Actuele editie": "Édition actuelle",
      "Albumhoezen": "Pochettes",
      "Coverarchief aanvullen": "Compléter l'archive des pochettes",
      "Actief": "Actif",
      "Hoezen gevonden": "Pochettes trouvées",
      "Nummers gecontroleerd": "Titres vérifiés",
      "Nog te controleren": "Encore à vérifier",
      "Controle voltooid": "Terminé",
      "Archiefopbouw": "Construction de l'archive",
      "Historisch archief opbouwen": "Construire l'archive historique",
      "Gepauzeerd": "En pause",
      "Totaal": "Total",
      "Start of hervat": "Démarrer ou reprendre",
      "Eén batch uitvoeren": "Exécuter un lot",
      "Pauzeren": "Pause",
      "Opslag & koppelingen": "Stockage et connexions",
      "Laatste editie": "Dernière édition",
      "Bekijk bron": "Voir la source",
      "Artiest": "Artiste",
      "Titel": "Titre",
      "Status": "Statut",
      "NIEUW": "NOUVEAU",
      "In wachtrij": "En attente",
      "Gedownload": "Téléchargé",
      "Wachtrij": "File d'attente",
      "Nu bezig": "En cours",
      "Actieve downloads": "Téléchargements actifs",
      "Zoeken": "Rechercher",
      "Downloaden": "Téléchargement",
      "Logboek": "Journal",
      "Laatste activiteit": "Dernière activité",
      "Mislukt": "Échec",
      "Mislukte downloads": "Téléchargements échoués",
      "Muziekarchief": "Archive musicale",
      "Onlangs opgeslagen": "Récemment enregistrés",
      "Archief zoeken": "Rechercher dans l'archive",
      "Vind een artiest of titel": "Trouver un artiste ou un titre",
      "Archief doorzoeken": "Rechercher dans l'archive",
      "Hitlijsten": "Classements",
      "Muzieklijsten beheren": "Gérer les classements musicaux",
      "Welke hitlijst wil je toevoegen?": "Quel classement voulez-vous ajouter ?",
      "Analyseren met Qwen": "Analyser avec Qwen",
      "Geconfigureerde hitlijsten": "Classements configurés",
      "Beheerinstellingen": "Paramètres de gestion",
      "Downloadmap": "Dossier de téléchargement",
      "Instellingen opslaan": "Enregistrer les paramètres"
    }
  };

  const savedText = new WeakMap();
  const savedPlaceholder = new WeakMap();

  function getLanguage() {
    const value = localStorage.getItem(storageKey);
    return languages.includes(value) ? value : "nl";
  }

  function translateValue(value, lang) {
    if (lang === "nl") return value;
    return translations[lang]?.[value] || value;
  }

  function translateNode(node, lang) {
    if (!node.nodeValue || !node.nodeValue.trim()) return;

    if (!savedText.has(node)) {
      savedText.set(node, node.nodeValue);
    }

    const original = savedText.get(node);
    const clean = original.trim();
    const before = original.slice(0, original.indexOf(clean));
    const after = original.slice(original.indexOf(clean) + clean.length);

    node.nodeValue = before + translateValue(clean, lang) + after;
  }

  function translatePage() {
    const lang = getLanguage();
    document.documentElement.lang = lang;

    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT
    );

    const nodes = [];

    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }

    nodes.forEach(node => translateNode(node, lang));

    document.querySelectorAll("[placeholder]").forEach(element => {
      if (!savedPlaceholder.has(element)) {
        savedPlaceholder.set(element, element.getAttribute("placeholder"));
      }

      const original = savedPlaceholder.get(element);
      element.setAttribute("placeholder", translateValue(original, lang));
    });

    document.querySelectorAll("[data-language]").forEach(button => {
      button.classList.toggle(
        "active",
        button.dataset.language === lang
      );
    });
  }

  function setLanguage(lang) {
    if (!languages.includes(lang)) return;

    localStorage.setItem(storageKey, lang);
    translatePage();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-language]").forEach(button => {
      button.addEventListener("click", () => {
        setLanguage(button.dataset.language);
      });
    });

    translatePage();

    const observer = new MutationObserver(() => {
      translatePage();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  });

  window.Top40I18n = {
    getLanguage,
    setLanguage,
    translatePage
  };
})();
