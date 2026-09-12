import re
import difflib

# Common titles and honorifics to strip during name normalization
HONORIFICS_PATTERN = re.compile(
    r'\b(?:mr|ms|mrs|miss|dr|prof|professor|shri|smt|master)\b\.?',
    re.IGNORECASE
)


def normalize_name(name):
    """
    Normalizes a student or certificate name for comparison:
    - Converts to lowercase.
    - Strips honorifics/prefixes.
    - Removes punctuation and symbols.
    - Normalizes and collapses multiple spaces.
    """
    if not name:
        return ""

    text = str(name).lower()
    # Strip honorifics
    text = HONORIFICS_PATTERN.sub('', text)
    # Remove non-alphanumeric except spaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Collapse multiple whitespaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def calculate_name_similarity(name1, name2):
    """
    Calculates fuzzy name similarity score between 0.0 and 1.0:
    - Exact match after normalization -> 1.0
    - Token sort match (e.g. "Nenavath Savitha" vs "Savitha Nenavath") -> 1.0
    - SequenceMatcher ratio on normalized strings
    - Substring containment match
    """
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)

    if not norm1 or not norm2:
        return 0.0

    if norm1 == norm2:
        return 1.0

    # Token sort comparison
    tokens1 = sorted(norm1.split())
    tokens2 = sorted(norm2.split())
    sorted_str1 = " ".join(tokens1)
    sorted_str2 = " ".join(tokens2)

    if sorted_str1 == sorted_str2:
        return 1.0

    # Direct SequenceMatcher ratio
    direct_ratio = difflib.SequenceMatcher(None, norm1, norm2).ratio()
    # Token-sorted SequenceMatcher ratio
    token_ratio = difflib.SequenceMatcher(None, sorted_str1, sorted_str2).ratio()

    # Substring containment check (e.g. if one name contains the other as whole tokens)
    containment_score = 0.0
    if norm1 in norm2 or norm2 in norm1:
        shorter_len = min(len(norm1), len(norm2))
        longer_len = max(len(norm1), len(norm2))
        if longer_len > 0:
            containment_score = shorter_len / longer_len

    return max(direct_ratio, token_ratio, containment_score)


def extract_candidate_names_from_text(raw_text):
    """
    Extracts candidate student name strings from certificate OCR text
    using header context patterns and clean text lines.
    """
    candidates = []
    if not raw_text:
        return candidates

    # Pattern 1: Certificate context headers
    header_patterns = [
        r'(?:presented\s+to|certify\s+that|awarded\s+to|conferred\s+upon|certifies\s+that|given\s+to)\s+([A-Za-z\s.\-]{3,50}?)(?:\s+(?:for|has|in|of|on|during|who|\n|,)|[.,\n]|$)',
        r'(?:this\s+is\s+to\s+certify\s+that)\s+([A-Za-z\s.\-]{3,50}?)(?:\s+(?:for|has|in|of|on|\n|,)|[.,\n]|$)',
        r'(?:name\s*[:\-]\s*)([A-Za-z\s.\-]{3,50})(?:\n|$|,)',
    ]

    for pat in header_patterns:
        for match in re.finditer(pat, raw_text, re.IGNORECASE):
            cand = match.group(1).strip()
            cleaned = normalize_name(cand)
            if cleaned and len(cleaned.split()) >= 1 and len(cleaned) >= 3:
                candidates.append(cand)

    # Pattern 2: Inspect lines in OCR text that resemble human names (1-4 words, alphabetic)
    lines = raw_text.splitlines()
    for line in lines:
        line_clean = line.strip()
        words = line_clean.split()
        if 1 <= len(words) <= 4:
            # Check if predominantly letters
            letters_only = re.sub(r'[^A-Za-z]', '', line_clean)
            if len(letters_only) >= 3 and len(letters_only) / max(len(line_clean), 1) > 0.7:
                # Exclude obvious non-name phrases
                lower_line = line_clean.lower()
                if not any(k in lower_line for k in ['certificate', 'participation', 'excellence', 'college', 'university', 'department', 'date', 'signature', 'coordinator', 'organizer', 'event', 'workshop', 'hackathon']):
                    candidates.append(line_clean)

    # Deduplicate while preserving order
    seen = set()
    unique_candidates = []
    for c in candidates:
        norm = normalize_name(c)
        if norm and norm not in seen:
            seen.add(norm)
            unique_candidates.append(c)

    return unique_candidates


def match_certificate_to_student(extracted_text, registered_students):
    """
    Matches certificate OCR text against registered students for an event.

    registered_students format:
    [
        {
            'student_id': user.id,
            'name': user.name,
            'roll_number': roll_number,
            'registration_id': reg.id
        },
        ...
    ]

    Returns:
    {
        'status': 'MATCHED_AUTOMATICALLY' | 'PENDING_MANUAL_REVIEW' | 'UNMATCHED',
        'matched_student_id': int or None,
        'matched_registration_id': int or None,
        'extracted_name': str or None,
        'confidence_score': float (0.0 to 1.0),
        'match_type': 'EXACT' | 'FUZZY' | 'ROLL_NUMBER' | 'NONE',
        'candidate_matches': list of { 'student_id', 'name', 'score' }
    }
    """
    from models.certificate import CertificateStatus

    if not registered_students:
        return {
            'status': CertificateStatus.UNMATCHED,
            'matched_student_id': None,
            'matched_registration_id': None,
            'extracted_name': None,
            'confidence_score': 0.0,
            'match_type': 'NONE',
            'candidate_matches': []
        }

    candidate_name_phrases = extract_candidate_names_from_text(extracted_text)
    norm_full_ocr = normalize_name(extracted_text)

    scored_candidates = []

    for reg_item in registered_students:
        st_name = reg_item.get('name', '')
        st_roll = (reg_item.get('roll_number') or '').strip().upper()
        norm_st_name = normalize_name(st_name)

        if not norm_st_name:
            continue

        best_score = 0.0
        best_extracted_phrase = None

        # 1. Exact or partial occurrence of full student name in OCR text
        if norm_st_name in norm_full_ocr:
            best_score = 1.0
            best_extracted_phrase = st_name
        else:
            # 2. Check similarity against candidate phrases extracted from text
            for phrase in candidate_name_phrases:
                sim = calculate_name_similarity(phrase, st_name)
                if sim > best_score:
                    best_score = sim
                    best_extracted_phrase = phrase

            # 3. Check similarity against full lines
            for line in extracted_text.splitlines():
                sim = calculate_name_similarity(line.strip(), st_name)
                if sim > best_score:
                    best_score = sim
                    best_extracted_phrase = line.strip()

        scored_candidates.append({
            'student_id': reg_item['student_id'],
            'registration_id': reg_item['registration_id'],
            'name': st_name,
            'roll_number': st_roll,
            'score': round(best_score, 2),
            'extracted_phrase': best_extracted_phrase
        })

    # Sort candidates by score descending
    scored_candidates.sort(key=lambda x: x['score'], reverse=True)

    if not scored_candidates:
        return {
            'status': CertificateStatus.UNMATCHED,
            'matched_student_id': None,
            'matched_registration_id': None,
            'extracted_name': None,
            'confidence_score': 0.0,
            'match_type': 'NONE',
            'candidate_matches': []
        }

    top_candidate = scored_candidates[0]
    top_score = top_candidate['score']
    runner_up_score = scored_candidates[1]['score'] if len(scored_candidates) > 1 else 0.0

    # Matching Decision Rules:
    # Rule 1: Exact Name Match (score >= 0.98)
    if top_score >= 0.98:
        # Check for ambiguity: if another student has a nearly identical name
        if runner_up_score >= 0.95:
            # Ambiguous match -> Pending Manual Review to prevent wrong assignment
            status = CertificateStatus.PENDING_MANUAL_REVIEW
            match_type = 'AMBIGUOUS_EXACT'
        else:
            status = CertificateStatus.MATCHED_AUTOMATICALLY
            match_type = 'EXACT'

    # Rule 2: Close / Fuzzy Name Match (0.85 <= score < 0.98)
    elif top_score >= 0.85:
        # Require a clear margin (> 0.15) over the runner up to auto-assign
        if (top_score - runner_up_score) >= 0.15:
            status = CertificateStatus.MATCHED_AUTOMATICALLY
            match_type = 'FUZZY'
        else:
            # Too close to call -> Pending Manual Review
            status = CertificateStatus.PENDING_MANUAL_REVIEW
            match_type = 'AMBIGUOUS_FUZZY'

    # Rule 3: Low Confidence Name Match (0.50 <= score < 0.85)
    elif top_score >= 0.50:
        status = CertificateStatus.PENDING_MANUAL_REVIEW
        match_type = 'LOW_CONFIDENCE'

    # Rule 4: No clear name match (< 0.50) -> check roll number fallback
    else:
        # Check if roll number appears in text
        matched_by_roll = None
        for reg_item in registered_students:
            roll = (reg_item.get('roll_number') or '').strip().upper()
            if roll and len(roll) >= 4 and roll in extracted_text.upper():
                matched_by_roll = reg_item
                break

        if matched_by_roll:
            top_candidate = {
                'student_id': matched_by_roll['student_id'],
                'registration_id': matched_by_roll['registration_id'],
                'name': matched_by_roll['name'],
                'roll_number': matched_by_roll['roll_number'],
                'score': 0.90,
                'extracted_phrase': f"Roll No: {matched_by_roll['roll_number']}"
            }
            status = CertificateStatus.MATCHED_AUTOMATICALLY
            match_type = 'ROLL_NUMBER'
            top_score = 0.90
        else:
            status = CertificateStatus.UNMATCHED
            match_type = 'NONE'

    matched_student_id = top_candidate['student_id'] if status == CertificateStatus.MATCHED_AUTOMATICALLY else None
    matched_registration_id = top_candidate['registration_id'] if status == CertificateStatus.MATCHED_AUTOMATICALLY else None

    return {
        'status': status,
        'matched_student_id': matched_student_id,
        'matched_registration_id': matched_registration_id,
        'suggested_student_id': top_candidate['student_id'] if status == CertificateStatus.PENDING_MANUAL_REVIEW else None,
        'extracted_name': top_candidate['extracted_phrase'],
        'confidence_score': top_score,
        'match_type': match_type,
        'candidate_matches': scored_candidates[:5]
    }
