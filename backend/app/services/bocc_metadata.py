"""Technical BOCC metadata extraction; no admission or indexing decisions."""
import re
import unicodedata


def extract_metadata(raw):
    text = unicodedata.normalize('NFKC', raw)
    nor = re.search(r'NOR\s*:\s*([A-Z]{4}\d{7}[A-Z])', text)
    header = text[:nor.start()] if nor else text[:1500]
    idccs = list(dict.fromkeys(
        code.zfill(4) for code in re.findall(r'IDCC\s*:\s*(\d{1,4})', header)
    ))
    title = re.search(
        r'(?m)^(?:Avenant\b|Accord\s+(?:du\b|interbranches?\s+du\b'
        r'|n°|de méthode\b|paritaire\b|de substitution\b)'
        r'|Protocole\s+d[’\x27]accord\s+du\b|Adhésion\b|Dénonciation\b'
        r'|Avis\s+d[’\x27]interprétation\b|Procès-verbal\b|Rectifi\s*catif\b'
        r'|Convention collective (?:nationale )?du\b)[\s\S]*', header,
    )
    return {
        'nor': nor.group(1) if nor else None,
        'idccs': idccs,
        'title': ' '.join(title.group().split()) if title else None,
        'header': header,
        'review_required': True,
    }
