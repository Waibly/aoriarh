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
// Written as a real user would ask, with concrete facts the user can edit
// before sending, so the first answer is specific rather than generic.
const PROFILE_SUGGESTIONS: Record<Profile, readonly ChatSuggestion[]> = {
  drh: [
    {
      id: "drh-rule",
      category: "understand",
      title: "Modifier les horaires d’une équipe",
      description: "Faut-il l’accord des salariés ?",
      prompt:
        "On veut faire passer une équipe de 8h-16h à 10h-18h. Faut-il l’accord des salariés ou peut-on l’imposer ?",
    },
    {
      id: "drh-document",
      category: "analyze",
      title: "Vérifier notre accord télétravail",
      description: "Est-il conforme à la loi et à la convention collective ?",
      prompt:
        "Voici notre accord télétravail. Est-il conforme à la loi et à notre convention collective ? Qu’est-ce qui manque ou pose problème ?",
      needsDocuments: true,
    },
    {
      id: "drh-writing",
      category: "write",
      title: "Une note sur le forfait jours",
      description: "Pour la direction qui veut l’appliquer aux cadres.",
      prompt:
        "La direction veut passer les cadres au forfait jours. Rédige une note d’une page pour elle : conditions à remplir, salariés concernés, suivi obligatoire et risques si c’est mal fait.",
    },
    {
      id: "drh-steps",
      category: "prepare",
      title: "Le calendrier d’un licenciement",
      description: "Chaque étape et chaque délai à respecter.",
      prompt:
        "Je dois licencier un salarié pour insuffisance professionnelle. Donne-moi le calendrier de la procédure étape par étape, avec les délais à respecter.",
    },
  ],
  charge_rh: [
    {
      id: "hr-rule",
      category: "understand",
      title: "Renouveler une période d’essai",
      description: "Est-ce possible, et jusqu’à quelle date ?",
      prompt:
        "Une salariée en CDI a commencé le 2 septembre avec une période d’essai de 2 mois. Peut-on la renouveler, et jusqu’à quelle date au plus tard ?",
    },
    {
      id: "hr-document",
      category: "analyze",
      title: "Relire un contrat avant signature",
      description: "Clauses manquantes, illégales ou contraires à la convention ?",
      prompt:
        "Relis ce contrat de travail avant signature. Y a-t-il des clauses manquantes, illégales ou contraires à notre convention collective ?",
      needsDocuments: true,
    },
    {
      id: "hr-writing",
      category: "write",
      title: "Accepter une dispense de préavis",
      description: "Le courrier de réponse et l’effet sur la paie.",
      prompt:
        "Un salarié qui a démissionné demande à partir 3 semaines avant la fin de son préavis. On accepte. Rédige le courrier de réponse et dis-moi ce que ça change pour sa paie.",
    },
    {
      id: "hr-steps",
      category: "prepare",
      title: "Organiser les élections du CSE",
      description: "Le rétroplanning avec les dates clés.",
      prompt:
        "Je dois organiser les élections du CSE dans une entreprise de 60 salariés. Fais-moi le rétroplanning avec les dates clés et ce qu’il faut faire à chaque étape.",
    },
  ],
  dirigeant: [
    {
      id: "manager-rule",
      category: "understand",
      title: "Un salarié ne vient plus",
      description: "Absent sans nouvelles : que faire, et dans quel ordre ?",
      prompt:
        "Un salarié ne vient plus depuis 4 jours et ne donne pas de nouvelles. Que dois-je faire, et dans quel ordre ?",
    },
    {
      id: "manager-document",
      category: "analyze",
      title: "Comprendre un contrat de travail",
      description: "Période d’essai, préavis, non-concurrence : en clair.",
      prompt:
        "Que dit ce contrat sur la période d’essai, le préavis et la clause de non-concurrence ? Explique-moi simplement.",
      needsDocuments: true,
    },
    {
      id: "manager-writing",
      category: "write",
      title: "Rédiger un avertissement",
      description: "Pour des retards répétés malgré un rappel oral.",
      prompt:
        "Rédige un avertissement pour un salarié arrivé en retard 5 fois ce mois-ci, malgré un rappel oral.",
    },
    {
      id: "manager-steps",
      category: "prepare",
      title: "Une rupture conventionnelle",
      description: "Combien ça coûte et quelles étapes suivre ?",
      prompt:
        "Un salarié me demande une rupture conventionnelle. Il a 5 ans d’ancienneté et gagne 2 800 € brut par mois. Combien ça me coûte au minimum, et quelles sont les étapes ?",
    },
  ],
  elu_cse: [
    {
      id: "cse-rule",
      category: "understand",
      title: "Justifier mes heures de délégation",
      description: "L’employeur peut-il l’exiger à l’avance ?",
      prompt:
        "Mon employeur exige que je justifie à l’avance l’utilisation de mes heures de délégation. A-t-il le droit ?",
    },
    {
      id: "cse-document",
      category: "analyze",
      title: "Un projet de réorganisation",
      description: "Le CSE doit-il être consulté ?",
      prompt:
        "Voici le projet de réorganisation présenté par la direction. Le CSE doit-il être consulté ? Quelles questions poser en réunion ?",
      needsDocuments: true,
    },
    {
      id: "cse-writing",
      category: "write",
      title: "Mettre un sujet à l’ordre du jour",
      description: "La demande à adresser pour la prochaine réunion.",
      prompt:
        "Rédige une demande d’inscription à l’ordre du jour du prochain CSE sur la hausse de la charge de travail dans l’équipe logistique.",
    },
    {
      id: "cse-steps",
      category: "prepare",
      title: "Le CSE est consulté sur un projet",
      description: "Quel délai pour rendre l’avis, et avec quelle aide ?",
      prompt:
        "La direction consulte le CSE sur un projet de déménagement. Quel délai avons-nous pour rendre notre avis, et pouvons-nous nous faire aider par un expert ?",
    },
  ],
  juriste: [
    {
      id: "legal-rule",
      category: "understand",
      title: "Passer d’un horaire de jour à un horaire de nuit",
      description: "La jurisprudence sur l’accord du salarié.",
      prompt:
        "Passage d’un horaire de jour à un horaire de nuit : que dit la jurisprudence sur la nécessité de l’accord du salarié ? Cite les arrêts de principe.",
    },
    {
      id: "legal-document",
      category: "analyze",
      title: "Une clause de mobilité est-elle valable ?",
      description: "Et permet-elle la mutation envisagée ?",
      prompt:
        "Cette clause de mobilité est-elle valable ? Permet-elle de muter le salarié de Lyon à Grenoble ?",
      needsDocuments: true,
    },
    {
      id: "legal-writing",
      category: "write",
      title: "Les risques d’un forfait jours mal suivi",
      description: "Une note avec la jurisprudence récente.",
      prompt:
        "Rédige une note sur les risques d’une convention de forfait jours sans suivi réel de la charge de travail, avec la jurisprudence récente.",
    },
    {
      id: "legal-steps",
      category: "prepare",
      title: "Un avertissement contesté",
      description: "Chronologie des faits et arguments de chaque partie.",
      prompt:
        "Un salarié conteste son avertissement. À partir des pièces jointes, fais la chronologie des faits et évalue les arguments de chaque partie.",
      needsDocuments: true,
    },
  ],
  consultant_rh: [
    {
      id: "consultant-rule",
      category: "understand",
      title: "Mettre en place le télétravail",
      description: "Accord, charte ou rien : quelles options pour mon client ?",
      prompt:
        "Mon client (45 salariés) veut mettre en place le télétravail. Accord, charte ou rien du tout : quelles options et quelles obligations ?",
    },
    {
      id: "consultant-document",
      category: "analyze",
      title: "Comparer deux versions d’un accord",
      description: "Les changements dans un tableau.",
      prompt:
        "Compare ces deux versions de l’accord télétravail de mon client. Montre les changements dans un tableau.",
      needsDocuments: true,
    },
    {
      id: "consultant-writing",
      category: "write",
      title: "Mon client veut supprimer une prime",
      description: "Peut-il le faire ? La réponse à lui envoyer.",
      prompt:
        "Mon client verse depuis 6 ans une prime de fin d’année qui n’est écrite nulle part. Peut-il la supprimer ? Rédige la réponse à lui envoyer.",
    },
    {
      id: "consultant-steps",
      category: "prepare",
      title: "Mon client passe les 50 salariés",
      description: "Ses nouvelles obligations, et à partir de quand.",
      prompt:
        "Mon client passe le seuil des 50 salariés. Liste ses nouvelles obligations et à partir de quand elles s’appliquent.",
    },
  ],
  comptable_paie: [
    {
      id: "payroll-rule",
      category: "understand",
      title: "Maintenir le salaire pendant un arrêt maladie",
      description: "Carence et maintien selon notre convention.",
      prompt:
        "Un salarié avec 3 ans d’ancienneté est en arrêt maladie depuis le 10 octobre. Combien de jours de carence, et quel maintien de salaire avec notre convention collective ?",
    },
    {
      id: "payroll-document",
      category: "analyze",
      title: "Lister les primes d’un accord",
      description: "Conditions de versement et mode de calcul.",
      prompt:
        "Liste les primes prévues par cet accord, avec leurs conditions de versement et leur mode de calcul.",
      needsDocuments: true,
    },
    {
      id: "payroll-writing",
      category: "write",
      title: "Une prime d’ancienneté contestée",
      description: "La règle et une réponse claire au salarié.",
      prompt:
        "Un salarié conteste le calcul de sa prime d’ancienneté. Explique-moi la règle de notre convention collective et rédige une réponse claire pour lui.",
    },
    {
      id: "payroll-steps",
      category: "prepare",
      title: "Le solde de tout compte d’un démissionnaire",
      description: "Le préavis et ce que doit contenir le solde.",
      prompt:
        "Un salarié démissionne avec 4 ans d’ancienneté. Quel préavis selon notre convention collective, et que doit contenir son solde de tout compte ?",
    },
  ],
  expert_comptable: [
    {
      id: "accountant-rule",
      category: "understand",
      title: "Mon client veut renouveler un CDD",
      description: "Déjà renouvelé une fois : est-ce encore possible ?",
      prompt:
        "Mon client veut renouveler un CDD de 6 mois pour accroissement d’activité, déjà renouvelé une fois. Est-ce possible ?",
    },
    {
      id: "accountant-document",
      category: "analyze",
      title: "Vérifier les heures supplémentaires d’un accord",
      description: "Les majorations respectent-elles la convention ?",
      prompt:
        "Les majorations d’heures supplémentaires prévues par cet accord respectent-elles la convention collective de mon client ?",
      needsDocuments: true,
    },
    {
      id: "accountant-writing",
      category: "write",
      title: "Rembourser les frais sans charges",
      description: "Un mail clair pour le client.",
      prompt:
        "Rédige un mail à mon client pour lui expliquer comment rembourser les repas et les trajets de ses salariés sans payer de cotisations.",
    },
    {
      id: "accountant-steps",
      category: "prepare",
      title: "Calculer une indemnité de licenciement",
      description: "Le minimum et les documents de fin de contrat.",
      prompt:
        "Un cadre de mon client va être licencié : 7 ans d’ancienneté, 3 500 € brut par mois. Calcule l’indemnité minimale et liste les documents de fin de contrat.",
    },
  ],
};

const COMMON_SUGGESTIONS: readonly ChatSuggestion[] = [
  {
    id: "common-rule",
    category: "understand",
    title: "Un congé pour mariage",
    description: "Combien de jours selon la loi et la convention ?",
    prompt:
      "Un salarié se marie le mois prochain. Combien de jours de congé a-t-il droit selon la loi et notre convention collective ?",
  },
  {
    id: "common-document",
    category: "analyze",
    title: "Les heures supplémentaires d’un accord",
    description: "Majorations et repos compensateur : est-ce conforme ?",
    prompt:
      "Que prévoit cet accord sur les heures supplémentaires (majorations, repos compensateur) ? Est-ce conforme à la loi et à notre convention collective ?",
    needsDocuments: true,
  },
  {
    id: "common-writing",
    category: "write",
    title: "Refuser une demande de congés",
    description: "Le peut-on, et comment le dire ?",
    prompt:
      "Un salarié demande une semaine de congés payés dans 10 jours, en pleine période chargée. Peut-on refuser ? Si oui, rédige la réponse.",
  },
  {
    id: "common-steps",
    category: "prepare",
    title: "Un salarié démissionne",
    description: "Préavis, documents et étapes du départ.",
    prompt:
      "Un salarié vient de démissionner. Quel préavis selon notre convention collective, et quels documents lui remettre à son départ ?",
  },
  {
    id: "compare",
    category: "analyze",
    title: "Comparer deux versions d’un accord",
    description: "Les changements dans un tableau.",
    prompt:
      "Compare ces deux versions de notre accord télétravail. Montre les changements dans un tableau.",
    needsDocuments: true,
  },
  {
    id: "clause",
    category: "analyze",
    title: "Une clause de non-concurrence est-elle valable ?",
    description: "Et que faut-il faire au départ du salarié ?",
    prompt:
      "Cette clause de non-concurrence est-elle valable ? Le salarié part dans un mois : que doit-on faire de cette clause ?",
    needsDocuments: true,
  },
  {
    id: "interview",
    category: "write",
    title: "Le retour d’un salarié après un arrêt",
    description: "Visite de reprise et trame d’entretien.",
    prompt:
      "Un salarié revient après 3 mois d’arrêt maladie. Faut-il une visite de reprise ? Prépare-moi aussi une trame pour l’entretien de retour.",
  },
  {
    id: "summary",
    category: "write",
    title: "Répondre à un avertissement contesté",
    description: "Maintenir la sanction, en bonne forme.",
    prompt:
      "Un salarié conteste par courrier l’avertissement reçu pour des retards répétés. Rédige une réponse qui maintient la sanction.",
  },
  {
    id: "clarify",
    category: "prepare",
    title: "Un salarié réclame des heures supplémentaires",
    description: "Que vérifier et que risque l’entreprise ?",
    prompt:
      "Un ancien salarié réclame 200 heures supplémentaires non payées sur 2 ans. Que dois-je vérifier, et que risque l’entreprise ?",
  },
  {
    id: "convention",
    category: "understand",
    title: "La prime d’ancienneté",
    description: "Ce que prévoit notre convention collective.",
    prompt:
      "Notre convention collective prévoit-elle une prime d’ancienneté ? À partir de quand et comment se calcule-t-elle ?",
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
      "Joignez un contrat, un accord ou un courrier (PDF, Word) et dites ce que vous voulez savoir.",
    needsDocuments: true,
    action: { kind: "attach", label: "Ajouter une pièce" },
  },
  {
    id: "comparison",
    title: "Comparez deux versions d’un document",
    description:
      "Joignez les deux versions : les changements ressortent dans un tableau.",
    needsDocuments: true,
    action: {
      kind: "attach",
      label: "Préparer une comparaison",
      prompt:
        "Compare ces deux versions et montre les changements dans un tableau.",
    },
  },
  {
    id: "writing",
    title: "Préparez un écrit à partir de votre situation",
    description:
      "Courrier, mail ou note : donnez les faits et le destinataire, le texte est rédigé pour vous.",
    action: {
      kind: "prompt",
      label: "Utiliser une trame",
      prompt:
        "Rédige un courrier.\nDestinataire : …\nSituation : …\nCe que je veux obtenir : …",
    },
  },
  {
    id: "convention",
    title: "Votre convention collective est prise en compte",
    description:
      "Si elle est renseignée pour votre entreprise, inutile de la citer : les réponses s’appuient dessus.",
  },
  {
    id: "context",
    title: "Donnez les faits, pas seulement le sujet",
    description:
      "Dates, ancienneté, type de contrat : plus la question est précise, plus la réponse l’est.",
    action: {
      kind: "prompt",
      label: "Utiliser une trame",
      prompt:
        "Situation : …\nDates et ancienneté : …\nType de contrat : …\nMa question : …",
    },
  },
  {
    id: "revision",
    title: "Demandez une autre version",
    description:
      "Après une réponse, demandez « plus court », « plus formel » ou « pour un salarié », dans la même conversation.",
  },
  {
    id: "structure",
    title: "Choisissez la forme de la réponse",
    description:
      "Tableau, liste d’étapes ou calendrier : demandez-le dans votre question.",
  },
  {
    id: "sources",
    title: "Lisez le texte exact",
    description:
      "Cliquez sur une référence citée pour ouvrir l’article, la convention ou l’arrêt utilisé.",
  },
  {
    id: "library",
    title: "Réutilisez une pièce déjà enregistrée",
    description:
      "Choisissez un document de l’entreprise dans la bibliothèque, sans l’importer à nouveau.",
    needsDocuments: true,
    action: { kind: "browse", label: "Choisir un document" },
  },
  {
    id: "dossier",
    title: "Un sujet qui dure ? Créez un dossier",
    description:
      "Faits, pièces et conversations restent réunis, et vos questions suivantes en tiennent compte.",
    action: { kind: "link", href: "/dossiers", label: "Voir mes dossiers" },
  },
  {
    id: "fiche",
    title: "Gardez une fiche pratique en PDF",
    description:
      "Sous une réponse, cliquez sur « Créer une fiche pratique » quand le bouton est proposé. Retrouvez-la dans « Mes fiches ».",
    action: { kind: "link", href: "/fiches", label: "Voir mes fiches" },
  },
];
