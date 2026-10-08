"""Official NAC categories reviewed for RH admission on 2026-10-08.

Mixed protection-sociale category 88 and non-salaried agricultural category 89H
remain review-only. Unknown categories are inventoried, never discarded.
Source: Judilibre /taxonomy NAC, archived in the documentary audit.
"""

ADMITTED_NAC = {
    "80J": "Contestation du motif non économique de la rupture du contrat de travail",
    "80K": "Contestation du motif économique de la rupture du contrat de travail",
    "80L": "Demande de prise d'acte de la rupture du contrat de travail",
    "80M": "Demande de résiliation ou de résolution judiciaire du contrat de travail formée par un salarié",
    "80N": "Demande de mise à la retraite formée par un salarié",
    "80O": "Demande de requalification du contrat de travail",
    "80P": "Demande en paiement de créances salariales sans contestation du motif de la rupture du contrat de "
    "travail",
    "80Q": "Demande d'annulation d'une sanction disciplinaire",
    "80R": "Demande d'autorisation judiciaire de congé particulier ou demande de congés formation",
    "80S": "Demande de remise de documents",
    "80T": "Demande en paiement de créances salariales en l'absence de rupture du contrat de travail",
    "80U": "Demande présentée par un employeur liée à la rupture du contrat de travail ou à des créances "
    "salariales ",
    "80V": "Demande dirigée par un salarié contre un autre salarié",
    "80W": "Contestation en matière de médecine du travail",
    "80Y": "Demande de nullité de la rupture du contrat de travail ",
    "80Z": "Contestation de la rupture du contrat de travail sur le fondement de la présomption de démission",
    "81A": "Demande relative à l'organisation des élections des institutions représentatives du personnel dans "
    "l'entreprise",
    "81B": "Demande relative à l'inscription sur les listes électorales ou sur la liste des candidats  pour "
    "l'élection des institutions représentatives du personnel dans l'entreprise",
    "81C": "Demande d'annulation du scrutin d'élection d'une institution représentative du personnel de "
    "l'entreprise ou d'un scrutin de révocation ",
    "81D": "Demande d'annulation de la désignation élective de représentants du personnel des institutions "
    "représentatives ou d'un scrutin de révocation",
    "81E": "Demande relative à la constitution, la composition ou l'inclusion dans un groupe ",
    "81F": "Demande relative à la désignation des représentants du personnel au comité de groupe",
    "81G": "Demande relative à l'élection de représentants des salariés au conseil d'une entreprise du secteur "
    "public ou d'une société privée",
    "81H": "Demande en révocation d'un administrateur salarié pour faute",
    "81I": "Demande relative à l'élection d'autres représentants du personnel",
    "81J": "Demande relative aux élections des conseillers prud'hommes",
    "81K": "Contestation de la décision administrative relative au scrutin sur sigle organisé dans les très "
    "petites entreprises",
    "82A": "Demande de moyens de fonctionnement d'une institution représentative du personnel",
    "82B": "Demande en exécution d'obligations corrélatives aux attributions de représentants du personnel",
    "82C": "Demande relative à la désignation, au mandat ou la rémunération d'un expert",
    "82D": "Demande en nullité d'une délibération d'une institution représentative",
    "82E": "Autres demandes des représentants du personnel",
    "82F": "Autres demandes contre une institution représentative en raison de son fonctionnement",
    "82G": "Demande relative à l'expression directe des salariés",
    "82H": "Demande relative à la personnalité juridique d'un syndicat",
    "82I": "Demande d'annulation de la désignation ou de la révocation d'un délégué syndical ou d'un "
    "représentant syndical au comité d'entreprise",
    "82J": "Autres demandes contre un syndicat",
    "83A": "Demande en paiement d'heures consacrées aux fonctions",
    "83B": "Demande d'annulation d'une sanction disciplinaire frappant un salarié protégé",
    "83C": "Demande d'indemnités ou de salaires  liée à la rupture autorisée ou non d'un contrat de travail "
    "d'un salarié protégé",
    "83G": "Demande de résiliation ou de résolution judiciaire du contrat de travail formée par un salarié "
    "protégé",
    "83H": "Autres demandes d'un salarié protégé",
    "83I": "Demande d'un employeur contre un salarié protégé",
    "84A": "Demande en annulation de la désignation du représentant des salariés ou des institutions "
    "représentatives du personnel",
    "84B": "Autres demandes relatives à la désignation du représentant des salariés ou des institutions "
    "représentatives du personnel",
    "84C": "Demande en annulation de la décision de remplacement du représentant des salariés ou des "
    "institutions représentatives du personnel",
    "84D": "Action en responsabilité civile exercée contre le représentant des salariés, des institutions "
    "représentatives ou des représentants du personnel, pour manquement à l'obligation de discrétion",
    "84E": "Demande consécutive à une autorisation de licenciements pour motif économique",
    "84J": "Constestation de la rupture du contrat de travail présentée après l'ouverture d'une procédure "
    "collective",
    "84K": "Demande d'indemnités ou de salaires sans contestation de la rupture du contrat de travail présentée "
    "après l'ouverture d'une procédure collective",
    "84L": "Demande en relevé de forclusion opposable à un salarié",
    "84M": "Demande de l'A.G.S. en paiement des cotisations contre un employeur soumis à l'obligation "
    "d'assurance des créances salariales",
    "84N": "Demande de l'A.G.S. d'un administrateur judiciaire, d'un représentant des créanciers, ou mandataire "
    "liquidateur contre un salarié",
    "85A": "Demande d'expulsion d'occupants des lieux de travail",
    "85B": "Demande tendant à la réouverture des locaux de travail",
    "85C": "Autres demandes de l'employeur relatives à un mouvement collectif",
    "85D": "Autres demandes d'un syndicat ou d'un salarié en matière de conflits collectifs",
    "86A": "Demande relative à l'ouverture ou au déroulement d'une négociation collective",
    "86B": "Demande en nullité d'une clause, d'une convention ou d'un accord collectif",
    "86C": "Demande en appréciation de validité d'une clause conventionnelle",
    "86D": "Demande en exécution d'engagements conventionnels, ou tendant à sanctionner leur inexécution",
    "86E": "Demande relative au fonctionnement d'un organisme créé par une convention ou un accord collectif de "
    "travail",
    "86F": "Demande en exécution d'un accord de conciliation, d'un accord sur une recommandation de médiateur, "
    "d'une sentence arbitrale, ou tendant à sanctionner leur inexécution",
    "86G": "Demande relative à la validité d'une clause d'un accord ou d'un accord de conciliation ou d'un "
    "accord sur une recommandation de médiateur",
    "86H": "Demande en réparation du dommage causé par une plateforme à responsabilité sociale à un travailleur "
    "indépendant en rapport avec son mandat de représentation",
    "86I": "Recours concernant la charte de responsabilité sociale des plateformes à responsabilité sociale ou "
    "la décision du directeur général du travail sur l’homologation de cette charte",
    "87A": "Demande relative à la validité, l'exécution ou la résiliation du contrat d'apprentissage formée par "
    "l'apprenti",
    "87B": "Demande relative à la validité, l'exécution ou la résiliation du contrat d'apprentissage formée par "
    "l'employeur",
    "87C": "Demande formée par un employeur ou un salarié contre un organisme de formation, un organisme "
    "paritaire collecteur agrée ou un fonds d'assurance formation",
    "87D": "Demande formée par un organisme de formation ou d'un fonds d'assurance- formation",
    "87E": "Demande relative au fonctionnement d'un organisme de formation professionnelle",
    "87F": " Autres demandes en matière d'apprentissage",
    "89A": "A.T.M.P. : Demande de prise en charge au titre des A.T.M.P. et/ou contestation relative au taux "
    "d'incapacité",
    "89B": "A.T.M.P. : Demande relative à la faute inexcusable de l'employeur",
    "89C": "A.T.M.P. : Demande en réparation supplémentaire pour faute intentionnelle de l'employeur",
    "89D": "A.T.M.P. : Recours contre une décision d'une caisse motivée par une faute inexcusable ou "
    "intentionnelle de la victime ou d'un de ses ayants-droit",
    "89E": "A.T.M.P. : Demande d'un employeur contestant une décision d'une caisse",
    "89F": "A.T.M.P. : Demande en paiement de cotisations d' A.T.M.P.",
    "89G": "A.T.M.P. : Demande en répétition de prestations ou de frais",
    "89I": "Demande tendant à faire ordonner une mesure préventive de la réalisation d'un risque professionnel",
    "89J": "Demande relative au compte personnel de prévention de la pénibilité",
    "89K": "Demande relative à l'exposition à un risque professionnel",
    "89L": "Tarification - Demande tendant à faire inscrire une maladie professionnelle au compte spécial ou "
    "aux charges techniques générales ",
    "89M": "Tarification - Demande tendant au retrait ou à la modification du compte employeur des coûts moyens "
    "relatifs à une maladie professionnelle ou un accident du travail",
    "89N": "Tarification - Demande relative à l'attribution d'un taux réduit pour le personnel exerçant des "
    "fonctions support de nature administrative au sein de l'entreprise",
    "89O": "Tarification - Contestation du taux de cotisation fondée sur le classement de l'entreprise",
    "89P": "Tarification - Contestation d'une décision portant sur une cotisation supplémentaire liée à un "
    "risque exceptionnel présenté par l'exploitation ou sur une cotisation complémentaire liée à une "
    "faute inexcusable de l'employeur",
    "89Q": "Tarification - Contestation du taux de cotisation fondée sur des motifs autres que les maladies "
    "professionnelles et accidents du travail",
    "89R": "Tarification - Autres demandes ou contestations relatives au taux de cotisation",
    "89Z": "Autres demandes en matière de risques professionnels",
}
