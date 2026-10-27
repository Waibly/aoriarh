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
      title: "Modifier les horaires d’une équipe",
      description:
        "Faut-il l’accord des salariés pour appliquer les nouveaux horaires ?",
      prompt:
        "Nous voulons modifier les horaires d’une équipe. Faut-il l’accord des salariés ? Aide-moi à examiner le changement envisagé avec les contrats, les accords disponibles et la convention collective de cette entreprise. Précise les informations nécessaires avant de conclure.",
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
      title: "Expliquer le forfait jours à la direction",
      description:
        "Quelles conditions présenter avant de retenir cette organisation ?",
      prompt:
        "La direction envisage de mettre en place des forfaits jours. Prépare une note sur les conditions à examiner dans cette entreprise, les salariés concernés et les obligations de suivi. Appuie-toi sur les textes et accords disponibles et demande-moi les éléments manquants.",
    },
    {
      id: "drh-steps",
      category: "prepare",
      title: "Un salarié refuse une mobilité",
      description: "Quelles options examiner avant de décider de la suite ?",
      prompt:
        "Un salarié refuse la mobilité que nous lui proposons. Aide-moi à examiner les options selon le changement envisagé, son contrat et les règles applicables. Demande-moi les faits utiles et précise les conditions et les conséquences de chaque démarche envisagée.",
    },
  ],
  charge_rh: [
    {
      id: "hr-rule",
      category: "understand",
      title: "Renouveler une période d’essai",
      description: "Est-ce possible pour ce salarié et à quelles conditions ?",
      prompt:
        "Peut-on renouveler la période d’essai de ce salarié ? Aide-moi à examiner les conditions et les délais à partir du contrat, de la convention collective et des dates utiles. Demande-moi les informations manquantes.",
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
      title: "Répondre à une dispense de préavis",
      description:
        "Un salarié veut partir plus tôt après sa démission. Comment lui répondre ?",
      prompt:
        "Un salarié démissionnaire demande à être dispensé de tout ou partie de son préavis. Aide-moi à examiner les conséquences des options possibles, puis à préparer une réponse. Demande-moi les dates, la demande reçue et la position de l’entreprise avant de rédiger.",
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
      title: "Examiner la période d’essai du contrat",
      description: "Que prévoit cette clause et quelles conditions examiner ?",
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
      title: "Embaucher en CDD pour un surcroît d’activité",
      description: "Ce recrutement est-il possible dans ma situation ?",
      prompt:
        "Je souhaite recruter en CDD pour faire face à un surcroît d’activité. Quelles conditions et quelles démarches examiner avant l’embauche ? Demande-moi la nature du besoin, la durée envisagée et les informations utiles à cette entreprise.",
    },
  ],
  elu_cse: [
    {
      id: "cse-rule",
      category: "understand",
      title: "Mes heures de délégation sont refusées",
      description: "L’employeur peut-il s’opposer à leur utilisation ?",
      prompt:
        "Mon employeur s’oppose à l’utilisation de mes heures de délégation. Quelles règles s’appliquent et quelles démarches envisager ? Demande-moi mon mandat, le motif donné par l’employeur et les circonstances avant d’examiner la situation.",
    },
    {
      id: "cse-document",
      category: "analyze",
      title: "La direction change les horaires",
      description: "Le CSE doit-il être consulté sur ce projet ?",
      prompt:
        "La direction prévoit de changer les horaires d’une équipe. À partir du projet que je joins, du contexte de l’entreprise et des accords disponibles, quelles obligations d’information ou de consultation du CSE faut-il examiner ? Précise les informations manquantes et les questions à poser.",
      needsDocuments: true,
    },
    {
      id: "cse-writing",
      category: "write",
      title: "Des congés sont refusés à certains salariés",
      description:
        "Quelles questions adresser à la direction sur les critères appliqués ?",
      prompt:
        "Des salariés signalent des différences dans l’acceptation de leurs demandes de congés. Aide-moi à préparer des questions à la direction sur les critères appliqués et les règles pertinentes pour mon mandat CSE. Demande-moi les situations et les éléments disponibles avant de rédiger.",
    },
    {
      id: "cse-steps",
      category: "prepare",
      title: "La charge de travail augmente",
      description: "Comment préparer un échange après une réorganisation ?",
      prompt:
        "Des salariés signalent une hausse de leur charge de travail après une réorganisation. En tant qu’élu CSE, quels faits et documents réunir, quelles prérogatives examiner et quelles questions préparer pour la direction ? Demande-moi les éléments utiles sur notre comité et la situation.",
    },
  ],
  juriste: [
    {
      id: "legal-rule",
      category: "understand",
      title: "Passer d’un horaire de jour à un horaire de nuit",
      description: "Quelle jurisprudence rechercher sur l’accord du salarié ?",
      prompt:
        "Quelle jurisprudence rechercher sur le passage d’un horaire de jour à un horaire de nuit et la nécessité de l’accord du salarié ? Présente les décisions disponibles, les faits qu’elles examinent et les éléments nécessaires pour les rapprocher de mon dossier.",
    },
    {
      id: "legal-document",
      category: "analyze",
      title: "Examiner une clause de mobilité",
      description: "Permet-elle le changement de lieu de travail envisagé ?",
      prompt:
        "Cette clause de mobilité permet-elle le changement de lieu de travail envisagé ? Examine le contrat que je joins et recherche les règles pertinentes. Demande-moi les lieux concernés et les circonstances, puis distingue la portée de la clause et ses conditions de mise en œuvre.",
      needsDocuments: true,
    },
    {
      id: "legal-writing",
      category: "write",
      title: "Expliquer les conditions du forfait jours aux RH",
      description: "Quels points examiner pour les salariés concernés ?",
      prompt:
        "Les RH souhaitent appliquer le forfait jours à certains salariés. Aide-moi à préparer une note sur les conditions d’éligibilité, les dispositions collectives et individuelles et les obligations de suivi à examiner. Demande-moi le contexte et les textes disponibles, puis présente les références et les points encore ouverts.",
    },
    {
      id: "legal-steps",
      category: "prepare",
      title: "Préparer un dossier de contestation d’un avertissement",
      description: "Quels faits et quelles pièces éclairent le différend ?",
      prompt:
        "Un salarié conteste un avertissement. À partir des pièces que je joins, reconstitue la chronologie pour préparer l’examen du différend. Attribue chaque élément à sa pièce et distingue les faits rapportés, les positions des parties et les informations manquantes.",
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
      title: "Comparer deux versions d’un accord télétravail",
      description: "Qu’est-ce qui change pour les salariés de mon client ?",
      prompt:
        "Compare les deux versions de l’accord télétravail que je joins pour mon client. Présente dans un tableau les changements sur l’accès au télétravail, son organisation et sa prise en charge, avec les passages concernés et les questions à approfondir.",
      needsDocuments: true,
    },
    {
      id: "consultant-writing",
      category: "write",
      title: "Mon client veut supprimer une prime",
      description: "Peut-il le faire et quelles démarches prévoir ?",
      prompt:
        "Mon client souhaite supprimer une prime versée régulièrement aux salariés. Aide-moi à déterminer son origine et les règles applicables à sa suppression, à partir de la convention collective et des documents disponibles. Quelles informations faut-il compléter avant de lui répondre ? Prépare ensuite une explication au client avec les références disponibles.",
    },
    {
      id: "consultant-steps",
      category: "prepare",
      title: "Mon client veut instaurer des forfaits jours",
      description: "Quelles conditions examiner avant la mise en place ?",
      prompt:
        "Mon client veut instaurer des forfaits jours. Quelles conditions examiner et quels documents réunir avant la mise en place ? Aide-moi à préciser les salariés concernés, les dispositions collectives disponibles et l’organisation du suivi dans l’entreprise cliente sélectionnée.",
    },
  ],
  comptable_paie: [
    {
      id: "payroll-rule",
      category: "understand",
      title: "Maintenir le salaire pendant un arrêt maladie",
      description:
        "Ce salarié y a-t-il droit selon sa situation et sa convention collective ?",
      prompt:
        "Ce salarié en arrêt maladie a-t-il droit au maintien de salaire ? Examine les règles légales et celles de la convention collective de cette entreprise. Demande-moi les dates, son ancienneté et les autres informations nécessaires, puis présente les conditions et les références disponibles.",
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
      title: "Expliquer une prime d’ancienneté au salarié",
      description:
        "Est-elle prévue pour lui et comment expliquer ses conditions ?",
      prompt:
        "Une prime d’ancienneté est-elle prévue pour ce salarié par la convention collective de cette entreprise ? Demande-moi les éléments utiles à l’examen de sa situation, puis prépare une explication au salarié sur les conditions applicables avec les références disponibles.",
    },
    {
      id: "payroll-steps",
      category: "prepare",
      title: "Préparer le départ après une démission",
      description:
        "Quel préavis et quels éléments prévoir pour le solde de tout compte ?",
      prompt:
        "Un salarié démissionne. Quelles informations réunir et quelles règles examiner pour le préavis, les sommes de fin de contrat et les documents à remettre ? Demande-moi sa situation et les dates utiles. Distingue les règles à rechercher de leur traitement dans le logiciel de paie.",
    },
  ],
  expert_comptable: [
    {
      id: "accountant-rule",
      category: "understand",
      title: "Mon client veut renouveler un CDD",
      description:
        "Est-ce possible avec ce motif, cette durée et cette convention collective ?",
      prompt:
        "Mon client souhaite renouveler un CDD. Est-ce possible dans sa situation ? Demande-moi le motif, les dates, les renouvellements déjà intervenus et les dispositions du contrat, puis examine les règles applicables à l’entreprise cliente sélectionnée.",
    },
    {
      id: "accountant-document",
      category: "analyze",
      title: "Examiner les majorations d’heures supplémentaires",
      description:
        "Comment l’accord du client s’articule-t-il avec sa convention collective ?",
      prompt:
        "Examine les dispositions sur les heures supplémentaires dans l’accord que je joins pour mon client. Comment les majorations prévues s’articulent-elles avec la convention collective et les règles légales ? Cite les passages utiles et précise les informations à compléter avant le traitement en paie.",
      needsDocuments: true,
    },
    {
      id: "accountant-writing",
      category: "write",
      title: "Expliquer les frais professionnels au client",
      description:
        "Quelles conditions de remboursement et d’exonération lui présenter ?",
      prompt:
        "Prépare une explication pour mon client sur les règles de remboursement des frais professionnels. Demande-moi les frais concernés et présente les conditions d’exonération avec les références disponibles.",
    },
    {
      id: "accountant-steps",
      category: "prepare",
      title: "Un salarié de mon client démissionne",
      description:
        "Quel préavis et quelles démarches préparer avec le client ?",
      prompt:
        "Un salarié de mon client démissionne. Quel préavis examiner et quelles démarches préparer avec le client ? Demande-moi la classification, l’ancienneté, les dates et les documents utiles, puis présente les règles et les points à traiter pour l’entreprise cliente sélectionnée.",
    },
  ],
};

const COMMON_SUGGESTIONS: readonly ChatSuggestion[] = [
  {
    id: "common-rule",
    category: "understand",
    title: "Un salarié demande un congé pour mariage",
    description:
      "Quelle durée prévoir selon la loi et la convention collective ?",
    prompt:
      "Un salarié demande un congé pour son mariage. Que prévoient la loi et la convention collective de cette entreprise sur sa durée et ses conditions ? Demande-moi les dates et les informations nécessaires à sa situation.",
  },
  {
    id: "common-document",
    category: "analyze",
    title: "Examiner les heures supplémentaires dans un accord",
    description:
      "Que prévoit ce document sur leur majoration et leur compensation ?",
    prompt:
      "Examine les dispositions sur les heures supplémentaires dans l’accord que je joins. Présente les passages sur leur majoration et leur compensation, puis recherche les règles utiles pour examiner leur application dans cette entreprise. Précise les informations manquantes.",
    needsDocuments: true,
  },
  {
    id: "common-writing",
    category: "write",
    title: "Répondre à une demande de congé tardive",
    description: "Quels éléments examiner avant d’accepter ou de refuser ?",
    prompt:
      "Un salarié a présenté une demande de congé peu avant la date souhaitée. Aide-moi à examiner les règles applicables et à préparer une réponse. Demande-moi le type de congé, les dates, les dispositions internes et les contraintes invoquées avant de rédiger.",
  },
  {
    id: "common-steps",
    category: "prepare",
    title: "Un salarié démissionne",
    description:
      "Quelles démarches et quels documents prévoir pour son départ ?",
    prompt:
      "Un salarié démissionne. Quelles démarches et quels documents prévoir pour son départ ? Demande-moi mon rôle, les dates et les éléments utiles à sa situation, puis présente les étapes à préparer au regard des règles applicables.",
  },
  {
    id: "compare",
    category: "analyze",
    title: "Repérer les changements d’un accord télétravail",
    description: "Qu’est-ce qui change entre ces deux versions ?",
    prompt:
      "Compare les deux versions de l’accord télétravail que je joins. Présente les changements sur l’accès au télétravail, son organisation et sa prise en charge, avec les passages concernés et les points à approfondir.",
    needsDocuments: true,
  },
  {
    id: "clause",
    category: "analyze",
    title: "Comprendre une clause de non-concurrence",
    description:
      "Que prévoit-elle et quelles conditions examiner pour son application ?",
    prompt:
      "Explique la clause de non-concurrence du contrat que je joins. Présente les obligations qu’elle prévoit et recherche les règles utiles pour examiner ses conditions de validité et d’application. Demande-moi les éléments nécessaires à la situation du salarié.",
    needsDocuments: true,
  },
  {
    id: "interview",
    category: "write",
    title: "Préparer un entretien de reprise après un arrêt maladie",
    description: "Quels sujets aborder avec le salarié lors de l’échange RH ?",
    prompt:
      "Aide-moi à préparer une trame d’entretien RH avec un salarié qui reprend après un arrêt maladie. Demande-moi mon rôle, le contexte de la reprise et les éléments utiles à l’organisation du travail. Prépare les sujets et questions à aborder dans cet échange, en distinguant celui-ci des visites relevant de la santé au travail.",
  },
  {
    id: "summary",
    category: "write",
    title: "Répondre à la contestation d’un avertissement",
    description:
      "Quels éléments du dossier examiner avant de rédiger la réponse ?",
    prompt:
      "Un salarié conteste un avertissement. Aide-moi à examiner les faits, les dates, le courrier reçu et les règles pertinentes, puis à préparer une réponse. Demande-moi les éléments du dossier et la position de l’entreprise avant de rédiger.",
  },
  {
    id: "clarify",
    category: "prepare",
    title: "Un salarié réclame des heures supplémentaires",
    description: "Quels faits et relevés réunir pour examiner sa demande ?",
    prompt:
      "Un salarié réclame le paiement d’heures supplémentaires. Quels faits, dates et relevés réunir pour examiner sa demande au regard des règles applicables ? Demande-moi mon rôle, son organisation du temps de travail et les éléments disponibles.",
  },
  {
    id: "convention",
    category: "understand",
    title: "Rechercher une prime d’ancienneté",
    description: "Que prévoit la convention collective pour ce salarié ?",
    prompt:
      "La convention collective de cette entreprise prévoit-elle une prime d’ancienneté pour ce salarié ? Demande-moi les éléments utiles à sa situation et présente les conditions d’attribution avec les références disponibles.",
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
