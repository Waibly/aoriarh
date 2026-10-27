import { PROFIL_METIER_OPTIONS } from "@/types/api";

type Profile = (typeof PROFIL_METIER_OPTIONS)[number]["value"];
export type DiscoveryCategory = "understand" | "analyze" | "write" | "prepare";

export interface ChatSuggestion {
  id: string;
  category: DiscoveryCategory;
  title: string;
  description: string;
  prompt: string;
  needsDocuments?: boolean;
}

export const DISCOVERY_CATEGORIES: Record<DiscoveryCategory, string> = {
  understand: "Comprendre",
  analyze: "Analyser",
  write: "Rédiger",
  prepare: "Préparer",
};

// Authored examples, selected only from the declared profile and available UI.
// They never inspect conversations or assess generated answers.
const PROFILE_SUGGESTIONS: Record<Profile, readonly ChatSuggestion[]> = {
  drh: [
    {
      id: "drh-rule",
      category: "understand",
      title: "Faire évoluer les horaires",
      description:
        "Faut-il l’accord du salarié avant de modifier ses horaires ?",
      prompt:
        "Un changement d’horaires nécessite-t-il l’accord du salarié ? Aide-moi à identifier les règles applicables et les informations nécessaires pour examiner ma situation.",
    },
    {
      id: "drh-document",
      category: "analyze",
      title: "Comparer accord et contrat",
      description:
        "Quelles différences entre notre accord télétravail et ce contrat ?",
      prompt:
        "Compare les dispositions sur le télétravail de l’accord et du contrat que je joins. Relève les différences et recherche les règles utiles pour examiner leur articulation.",
      needsDocuments: true,
    },
    {
      id: "drh-writing",
      category: "write",
      title: "Préparer une note à la direction",
      description:
        "Comment présenter cette situation et les options à la direction ?",
      prompt:
        "Aide-moi à préparer une note pour la direction sur une situation RH. Demande-moi les faits, le destinataire et l’objectif nécessaires, puis présente les règles pertinentes, les options à examiner et les informations manquantes.",
    },
    {
      id: "drh-steps",
      category: "prepare",
      title: "Préparer une réunion RH",
      description:
        "Quelles questions préparer avant de discuter d’une réorganisation ?",
      prompt:
        "Aide-moi à préparer une réunion sur un projet de réorganisation. Quelles informations réunir et quelles questions examiner au regard du projet et du contexte de l’entreprise ?",
    },
  ],
  charge_rh: [
    {
      id: "hr-rule",
      category: "understand",
      title: "Répondre à une demande de congé",
      description: "Quels congés prévoir pour un mariage ou une naissance ?",
      prompt:
        "Quels congés pour événement familial prévoient la loi et la convention collective de cette entreprise ? Demande-moi l’événement concerné et les informations utiles avant d’examiner la demande.",
    },
    {
      id: "hr-document",
      category: "analyze",
      title: "Examiner une lettre de démission",
      description: "Quelles dates et demandes apparaissent dans cette lettre ?",
      prompt:
        "Examine la lettre de démission que je joins. Relève les dates et les demandes exprimées, puis indique les informations et les règles à examiner avant de répondre.",
      needsDocuments: true,
    },
    {
      id: "hr-writing",
      category: "write",
      title: "Rédiger une réponse au salarié",
      description: "Comment répondre à une demande de télétravail ?",
      prompt:
        "Aide-moi à préparer une réponse à une demande de télétravail. Demande-moi la demande reçue, le contexte et les dispositions disponibles avant de rédiger le projet de réponse.",
    },
    {
      id: "hr-steps",
      category: "prepare",
      title: "Organiser une embauche",
      description:
        "Quels documents et étapes prévoir pour l’arrivée d’un salarié ?",
      prompt:
        "Aide-moi à préparer une liste des étapes et des documents pour une embauche. Demande-moi le type de contrat, la date envisagée et les informations nécessaires au contexte de cette entreprise.",
    },
  ],
  dirigeant: [
    {
      id: "manager-rule",
      category: "understand",
      title: "Réagir à une absence inexpliquée",
      description:
        "Que vérifier avant de réagir à une absence sans explication ?",
      prompt:
        "Un salarié est absent sans explication. Quels faits et quelles règles dois-je examiner avant de réagir ? Aide-moi à préciser la situation et les premières démarches à envisager.",
    },
    {
      id: "manager-document",
      category: "analyze",
      title: "Comprendre une clause du contrat",
      description: "Que prévoit la période d’essai dans ce contrat ?",
      prompt:
        "Explique-moi la clause de période d’essai du contrat que je joins. Distingue ce que prévoit la clause et les conditions légales ou conventionnelles à examiner.",
      needsDocuments: true,
    },
    {
      id: "manager-writing",
      category: "write",
      title: "Répondre à une demande d’horaires",
      description:
        "Comment répondre à un salarié qui veut changer ses horaires ?",
      prompt:
        "Aide-moi à répondre à une demande de changement d’horaires d’un salarié. Demande-moi son contenu, les contraintes de l’entreprise et le résultat souhaité avant de préparer un email.",
    },
    {
      id: "manager-steps",
      category: "prepare",
      title: "Préparer ma première embauche",
      description:
        "Quelles démarches préparer pour recruter mon premier salarié ?",
      prompt:
        "Je prépare ma première embauche. Par quoi commencer ? Demande-moi les informations utiles et prépare une liste d’étapes adaptée à mon entreprise.",
    },
  ],
  elu_cse: [
    {
      id: "cse-rule",
      category: "understand",
      title: "Comprendre les heures de délégation",
      description:
        "Comment utiliser mes heures de délégation dans le cadre de mon mandat ?",
      prompt:
        "Quelles règles encadrent l’utilisation des heures de délégation dans ma situation d’élu CSE ? Demande-moi mon mandat et les éléments nécessaires au contexte.",
    },
    {
      id: "cse-document",
      category: "analyze",
      title: "Examiner un projet transmis au CSE",
      description:
        "Que prévoit ce projet et quelles informations demander à la direction ?",
      prompt:
        "Résume le projet transmis au CSE que je joins. Présente les changements annoncés, les conséquences décrites pour les salariés et les informations à demander pour préparer son examen.",
      needsDocuments: true,
    },
    {
      id: "cse-writing",
      category: "write",
      title: "Préparer des questions à la direction",
      description:
        "Comment formuler les questions des élus sur un projet de l’entreprise ?",
      prompt:
        "Aide-moi à rédiger des questions à adresser à la direction sur un projet concernant les salariés. Demande-moi le projet et les préoccupations à traiter du point de vue de mon mandat CSE.",
    },
    {
      id: "cse-steps",
      category: "prepare",
      title: "Préparer l’examen d’une réclamation",
      description:
        "Quels faits et éléments réunir pour examiner la demande d’un salarié ?",
      prompt:
        "En tant qu’élu CSE, comment préparer l’examen d’une réclamation d’un salarié ? Aide-moi à réunir les faits et à identifier les règles et les démarches pertinentes pour mon mandat.",
    },
  ],
  juriste: [
    {
      id: "legal-rule",
      category: "understand",
      title: "Approfondir une question juridique",
      description:
        "Quelles décisions distinguent modification du contrat et changement des conditions de travail ?",
      prompt:
        "Quelle jurisprudence rechercher pour distinguer modification du contrat de travail et changement des conditions de travail ? Présente les distinctions et les références disponibles, en précisant les faits nécessaires à leur application.",
    },
    {
      id: "legal-document",
      category: "analyze",
      title: "Articuler accord et convention",
      description:
        "Comment cet accord s’articule-t-il avec la convention collective ?",
      prompt:
        "Analyse l’articulation entre l’accord d’entreprise que je joins et les dispositions conventionnelles pertinentes. Demande-moi le point à traiter si nécessaire et distingue les textes disponibles des informations manquantes.",
      needsDocuments: true,
    },
    {
      id: "legal-writing",
      category: "write",
      title: "Rédiger une note juridique",
      description:
        "Comment structurer les faits, les références et les points encore ouverts ?",
      prompt:
        "Aide-moi à préparer une note juridique à partir d’une situation. Demande-moi les faits et la question à traiter, puis présente les règles, les références disponibles, les nuances et les points encore ouverts.",
    },
    {
      id: "legal-steps",
      category: "prepare",
      title: "Reconstituer la chronologie",
      description:
        "Dans quel ordre les faits se sont-ils déroulés, d’après les pièces ?",
      prompt:
        "À partir des pièces que je joins, reconstitue la chronologie de la situation. Attribue chaque fait à sa pièce et relève les contradictions ou informations manquantes sans les résoudre à ma place.",
      needsDocuments: true,
    },
  ],
  consultant_rh: [
    {
      id: "consultant-rule",
      category: "understand",
      title: "Faire évoluer le télétravail",
      description:
        "Quelles règles examiner avant de modifier le télétravail chez mon client ?",
      prompt:
        "Quelles règles examiner avant de faire évoluer le télétravail chez mon client ? Aide-moi à préciser son projet et les dispositions applicables à l’entreprise sélectionnée.",
    },
    {
      id: "consultant-document",
      category: "analyze",
      title: "Comparer deux versions d’un accord",
      description:
        "Qu’est-ce qui change entre l’ancienne et la nouvelle version ?",
      prompt:
        "Compare les deux versions de l’accord que je joins. Présente les changements dans un tableau avec les passages concernés et les questions à approfondir.",
      needsDocuments: true,
    },
    {
      id: "consultant-writing",
      category: "write",
      title: "Préparer une restitution client",
      description:
        "Comment présenter les constats et les options à discuter avec mon client ?",
      prompt:
        "Aide-moi à préparer une note de restitution pour mon client. Demande-moi les éléments de la mission, puis distingue les constats documentés, les points à confirmer et les options à discuter.",
    },
    {
      id: "consultant-steps",
      category: "prepare",
      title: "Cadrer une mission RH",
      description:
        "Quelles questions poser au client avant une mission sur le temps de travail ?",
      prompt:
        "Prépare les questions de cadrage d’une mission sur le temps de travail chez mon client : objectifs, pratiques actuelles, périmètre, documents et informations nécessaires.",
    },
  ],
  comptable_paie: [
    {
      id: "payroll-rule",
      category: "understand",
      title: "Examiner le maintien de salaire",
      description:
        "Que prévoit la convention collective pendant un arrêt maladie ?",
      prompt:
        "Arrêt maladie : quelles règles de maintien de salaire prévoit la convention collective de cette entreprise ? Précise les conditions, les informations nécessaires et les références disponibles.",
    },
    {
      id: "payroll-document",
      category: "analyze",
      title: "Retrouver les règles d’une prime",
      description:
        "Quelles conditions de prime figurent dans le contrat et l’accord ?",
      prompt:
        "Retrouve les dispositions sur les primes dans le contrat et l’accord que je joins. Présente leurs conditions telles qu’elles figurent dans les pièces et les points à préciser.",
      needsDocuments: true,
    },
    {
      id: "payroll-writing",
      category: "write",
      title: "Expliquer une règle au salarié",
      description:
        "Comment expliquer une règle de prime d’ancienneté au salarié ?",
      prompt:
        "Aide-moi à préparer une explication au salarié sur une règle de prime d’ancienneté. Demande-moi sa question et les éléments utiles, puis prépare un texte clair avec les références disponibles.",
    },
    {
      id: "payroll-steps",
      category: "prepare",
      title: "Préparer le départ d’un salarié",
      description:
        "Quelles informations réunir pour le préavis et les indemnités ?",
      prompt:
        "Départ d’un salarié : quelles informations réunir et quelles règles examiner pour le préavis et les indemnités ? Distingue les règles à rechercher de leur traitement dans le logiciel de paie.",
    },
  ],
  expert_comptable: [
    {
      id: "accountant-rule",
      category: "understand",
      title: "Conseiller un client sur un CDD",
      description:
        "Quels points examiner avant le recrutement en CDD de mon client ?",
      prompt:
        "Mon client envisage un CDD : quelles conditions faut-il examiner ? Demande-moi le motif, la durée et les informations utiles, en tenant compte de l’entreprise cliente sélectionnée.",
    },
    {
      id: "accountant-document",
      category: "analyze",
      title: "Examiner un accord pour la paie",
      description:
        "Quelles dispositions sur le temps de travail peuvent avoir un effet en paie ?",
      prompt:
        "Examine l’accord sur le temps de travail que je joins pour mon client. Quels passages peuvent avoir des conséquences en paie et quelles informations faut-il encore examiner ?",
      needsDocuments: true,
    },
    {
      id: "accountant-writing",
      category: "write",
      title: "Préparer une explication au client",
      description:
        "Comment expliquer les remboursements de frais professionnels à mon client ?",
      prompt:
        "Prépare une explication pour mon client sur les règles de remboursement des frais professionnels. Demande-moi les frais concernés et présente les conditions d’exonération avec les références disponibles.",
    },
    {
      id: "accountant-steps",
      category: "prepare",
      title: "Préparer un rendez-vous social",
      description:
        "Quelles questions poser au client pour préparer son embauche ?",
      prompt:
        "Aide-moi à préparer un rendez-vous avec mon client sur les questions sociales d’une embauche. Prépare les questions à lui poser, les documents à réunir et les points à examiner pour son entreprise.",
    },
  ],
};

const COMMON_SUGGESTIONS: readonly ChatSuggestion[] = [
  {
    id: "common-rule",
    category: "understand",
    title: "Comprendre une règle de congé",
    description:
      "Quelles règles examiner pour répondre à une demande de congé ?",
    prompt:
      "Aide-moi à comprendre les règles applicables à une demande de congé. Demande-moi le type de congé et les informations nécessaires au contexte de cette entreprise.",
  },
  {
    id: "common-document",
    category: "analyze",
    title: "Résumer un document RH",
    description:
      "Quels sont les points essentiels, les dates et les questions ouvertes ?",
    prompt:
      "Résume le document que je joins. Fais ressortir son objet, les points principaux, les dates et les questions laissées ouvertes, en restant dans le contenu de la pièce.",
    needsDocuments: true,
  },
  {
    id: "common-writing",
    category: "write",
    title: "Préparer un email ou un courrier",
    description:
      "Comment formuler un message adapté à la situation et au destinataire ?",
    prompt:
      "Aide-moi à préparer un email ou un courrier sur une situation RH. Demande-moi les faits, mon rôle, le destinataire et le résultat attendu avant de rédiger.",
  },
  {
    id: "common-steps",
    category: "prepare",
    title: "Organiser les prochaines étapes",
    description:
      "Quels éléments réunir et quelles démarches envisager pour cette situation ?",
    prompt:
      "Aide-moi à organiser les prochaines étapes d’une situation RH. Demande-moi mon rôle et le contexte, puis distingue les informations à réunir, les règles à examiner et les actions à envisager.",
  },
  {
    id: "compare",
    category: "analyze",
    title: "Comparer deux documents",
    description:
      "Quelles différences entre les deux pièces sur le point qui m’intéresse ?",
    prompt:
      "Compare les deux documents que je joins sur le point que je souhaite examiner. Demande-moi ce point si nécessaire et présente les différences avec les passages concernés.",
    needsDocuments: true,
  },
  {
    id: "clause",
    category: "analyze",
    title: "Expliquer une clause",
    description: "Que dit cette clause et quelles règles faut-il examiner ?",
    prompt:
      "Explique la clause que je souhaite examiner dans le document joint. Distingue ce qui est écrit dans la pièce et les règles à rechercher pour comprendre son application.",
    needsDocuments: true,
  },
  {
    id: "interview",
    category: "write",
    title: "Préparer une trame d’entretien",
    description: "Quelles questions poser pour préparer cet échange ?",
    prompt:
      "Aide-moi à préparer une trame d’entretien pour une situation RH. Demande-moi mon rôle, le sujet et l’objectif de l’échange avant de proposer les questions.",
  },
  {
    id: "summary",
    category: "write",
    title: "Structurer une synthèse",
    description:
      "Comment présenter les faits et les prochaines étapes dans un tableau ?",
    prompt:
      "Aide-moi à synthétiser une situation RH dans un tableau : faits, informations manquantes, points à examiner et prochaines étapes. Demande-moi les éléments de la situation.",
  },
  {
    id: "clarify",
    category: "prepare",
    title: "Préciser une situation RH",
    description:
      "Quelles informations apporter avant d’examiner ma situation ?",
    prompt:
      "Aide-moi à préciser une situation RH avant de l’analyser. Pose-moi les questions utiles sur les faits, les dates, mon rôle et le résultat recherché.",
  },
  {
    id: "convention",
    category: "understand",
    title: "Explorer la convention collective",
    description:
      "Que prévoit la convention collective sur le sujet qui m’intéresse ?",
    prompt:
      "Aide-moi à retrouver les dispositions de la convention collective de cette entreprise sur un sujet. Demande-moi le sujet et précise les conditions d’application et les références disponibles.",
  },
];

export function getChatSuggestions(
  profile: string | null,
  documentsAvailable: boolean
) {
  const selected =
    profile && Object.hasOwn(PROFILE_SUGGESTIONS, profile)
      ? PROFILE_SUGGESTIONS[profile as Profile]
      : COMMON_SUGGESTIONS.slice(0, 4);
  const clarify = COMMON_SUGGESTIONS.find((item) => item.id === "clarify")!;
  const featured = selected.map((item) =>
    item.needsDocuments && !documentsAvailable
      ? item.category === "prepare"
        ? COMMON_SUGGESTIONS[3]
        : clarify
      : item
  );
  const ids = new Set(featured.map((item) => item.id));
  const library = [
    ...featured,
    ...COMMON_SUGGESTIONS.filter((item) => !ids.has(item.id)),
  ].filter((item) => !item.needsDocuments || documentsAvailable);
  return { featured, library };
}

type TipAction =
  | { kind: "prompt"; prompt: string; label: string }
  | { kind: "attach"; prompt?: string; label: string }
  | { kind: "browse"; label: string }
  | { kind: "link"; href: string; label: string };

export interface DiscoveryTip {
  id: string;
  title: string;
  description: string;
  action?: TipAction;
  needsDocuments?: boolean;
}

export const DISCOVERY_TIPS: readonly DiscoveryTip[] = [
  {
    id: "documents",
    title: "Analysez aussi vos documents",
    description:
      "Joignez un PDF, Word ou texte et indiquez le point à examiner.",
    needsDocuments: true,
    action: { kind: "attach", label: "Ajouter une pièce" },
  },
  {
    id: "comparison",
    title: "Comparez deux versions d’un document",
    description:
      "Demandez les changements et les passages concernés dans un tableau.",
    needsDocuments: true,
    action: {
      kind: "attach",
      label: "Préparer une comparaison",
      prompt:
        "Compare les deux versions du document que je vais joindre et présente les changements dans un tableau avec les passages concernés.",
    },
  },
  {
    id: "writing",
    title: "Préparez un écrit à partir de votre situation",
    description:
      "Email, courrier, note RH ou trame d’entretien : précisez le résultat attendu.",
    action: {
      kind: "prompt",
      label: "Préparer un écrit",
      prompt:
        "Aide-moi à préparer un écrit sur une situation RH. Demande-moi les faits, mon rôle, le destinataire et le résultat attendu avant de rédiger.",
    },
  },
  {
    id: "recipient",
    title: "Précisez à qui vous écrivez",
    description:
      "Un salarié, la direction ou un client : le destinataire aide à adapter le texte.",
    action: {
      kind: "prompt",
      label: "Utiliser une trame",
      prompt:
        "Je souhaite préparer un message. Mon rôle : …\nDestinataire : …\nSituation et faits : …\nRésultat attendu : …",
    },
  },
  {
    id: "revision",
    title: "Retravaillez un texte dans la conversation",
    description:
      "Après une proposition, demandez une version plus courte, plus détaillée ou adaptée à un autre destinataire.",
  },
  {
    id: "structure",
    title: "Choisissez la forme de votre synthèse",
    description:
      "Demandez un tableau, une liste d’étapes ou une synthèse des faits.",
    action: {
      kind: "prompt",
      label: "Préparer une synthèse",
      prompt:
        "Aide-moi à présenter une situation RH dans un tableau : faits, points à examiner, informations manquantes et prochaines étapes. Demande-moi les éléments utiles.",
    },
  },
  {
    id: "sources",
    title: "Ouvrez les références d’une réponse",
    description:
      "Cliquez sur une référence citée pour consulter le passage utilisé et approfondir votre lecture.",
  },
  {
    id: "library",
    title: "Réutilisez une pièce déjà enregistrée",
    description:
      "Sélectionnez un document de l’entreprise dans la bibliothèque, sans l’importer à nouveau.",
    needsDocuments: true,
    action: { kind: "browse", label: "Choisir un document" },
  },
  {
    id: "dossier",
    title: "Un sujet qui évolue ? Créez un dossier",
    description:
      "Réunissez les faits, les pièces et les conversations pour poursuivre le travail sur la même situation.",
    action: { kind: "link", href: "/dossiers", label: "Voir mes dossiers" },
  },
  {
    id: "continuity",
    title: "Complétez le dossier quand la situation évolue",
    description:
      "Ajoutez la nouvelle pièce ou corrigez un fait, puis précisez ce qui a changé dans votre prochaine question.",
    action: { kind: "link", href: "/dossiers", label: "Retrouver un dossier" },
  },
  {
    id: "fiche",
    title: "Gardez une fiche pratique en PDF",
    description:
      "Sous une réponse éligible, utilisez « Créer une fiche pratique ». Retrouvez-la ensuite dans « Mes fiches ».",
    action: { kind: "link", href: "/fiches", label: "Voir mes fiches" },
  },
  {
    id: "context",
    title: "Décrivez la situation avec vos mots",
    description:
      "Les dates, le contrat concerné et le résultat attendu sont de bons points de départ.",
    action: {
      kind: "prompt",
      label: "Utiliser une trame",
      prompt:
        "Mon rôle : …\nSituation : …\nDates utiles : …\nContrat et documents disponibles : …\nCe que je souhaite obtenir : …",
    },
  },
];
