from __future__ import print_function, division

import argparse
import math
import os
import pickle
import re
import tempfile
from collections import Counter

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
except ImportError:
    class _NoColour(object):
        RED = BLACK = BLUE = GREEN = YELLOW = MAGENTA = CYAN = WHITE = ''
        RESET_ALL = ''

    Fore = _NoColour()
    Style = _NoColour()


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

SWITCHER = {
    'r': Fore.RED,
    'bk': Fore.BLACK,
    'b': Fore.BLUE,
    'g': Fore.GREEN,
    'y': Fore.YELLOW,
    'm': Fore.MAGENTA,
    'c': Fore.CYAN,
    'w': Fore.WHITE
}


def paint(text, color='r'):
    """Return text with an optional foreground colour."""
    text = str(text)
    if color in SWITCHER:
        return SWITCHER[color] + text + Style.RESET_ALL
    return text


TAG = paint('TF-IDF-GENE/', 'b')

# Keeps normal words and contractions such as "don't".
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_']+", re.UNICODE)


# ---------------------------------------------------------------------------
# TF-IDF index
# ---------------------------------------------------------------------------

class TfidfIndex(object):
    """
    Stores raw term counts so TF-IDF can be correctly recalculated after
    additional documents are appended.

    Pickle files should only be loaded from trusted sources.
    """

    FORMAT_NAME = 'tfidf-index'
    VERSION = 2

    def __init__(self, lowercase=False, smooth_idf=True):
        self.lowercase = lowercase
        self.smooth_idf = smooth_idf

        # One Counter/dict per document. Needed for safe recalculation later.
        self.documents = []

        # term -> number of documents containing that term
        self.document_frequency = Counter()

    @property
    def document_count(self):
        return len(self.documents)

    def tokenize(self, text):
        """Convert one document line into tokens."""
        if self.lowercase:
            text = text.lower()
        return TOKEN_PATTERN.findall(text)

    def add_document(self, text):
        """Add one document represented as a string."""
        tokens = self.tokenize(text)

        # Ignore empty lines rather than adding empty documents.
        if not tokens:
            return False

        counts = Counter(tokens)
        self.documents.append(counts)

        # Document frequency must increment only once per word per document.
        for term in counts:
            self.document_frequency[term] += 1

        return True

    def add_files(self, file_names, encoding='utf-8'):
        """
        Add documents from files. Every non-empty line is treated as a document.

        Returns:
            int: number of documents successfully added.
        """
        added = 0

        for file_name in file_names:
            if not os.path.isfile(file_name):
                raise IOError('Input file does not exist: {0}'.format(file_name))

            try:
                with open(file_name, 'r', encoding=encoding) as source_file:
                    for line in source_file:
                        if self.add_document(line):
                            added += 1
            except UnicodeDecodeError:
                raise UnicodeDecodeError(
                    'utf-8',
                    b'',
                    0,
                    1,
                    'Could not decode "{0}". Try another encoding.'.format(file_name)
                )

        return added

    def get_idf_values(self):
        """
        Return true IDF weights.

        Smoothed IDF:
            log((1 + N) / (1 + df)) + 1

        This avoids division-by-zero and gives useful positive scores.
        """
        total_documents = float(self.document_count)

        if total_documents == 0:
            return {}

        idf_values = {}

        for term, df in self.document_frequency.items():
            if self.smooth_idf:
                idf_values[term] = math.log(
                    (1.0 + total_documents) / (1.0 + float(df))
                ) + 1.0
            else:
                idf_values[term] = math.log(total_documents / float(df))

        return idf_values

    def transform(self):
        """
        Build a sparse TF-IDF dictionary for every document.

        TF is calculated correctly as:
            term_count / total_number_of_tokens_in_document
        """
        idf_values = self.get_idf_values()
        tf_idf = []

        for counts in self.documents:
            total_terms = float(sum(counts.values()))

            if total_terms == 0:
                tf_idf.append({})
                continue

            vector = {}

            for term, count in counts.items():
                term_frequency = float(count) / total_terms
                vector[term] = term_frequency * idf_values[term]

            tf_idf.append(vector)

        return tf_idf

    def export_legacy_style(self):
        """
        Keeps compatibility with the old function output.

        Returns:
            idf: document-frequency dictionary, not mathematical IDF weights.
            tf_idf: list of sparse TF-IDF dictionaries.
        """
        return dict(self.document_frequency), self.transform()

    def save(self, file_path):
        """Save index safely using an atomic replace."""
        if not file_path.endswith('.tfidfpkl'):
            raise ValueError(
                'Please use a .tfidfpkl extension. Received: {0}'.format(file_path)
            )

        destination_dir = os.path.dirname(os.path.abspath(file_path))

        if not os.path.isdir(destination_dir):
            os.makedirs(destination_dir)

        payload = {
            'format': self.FORMAT_NAME,
            'version': self.VERSION,
            'lowercase': self.lowercase,
            'smooth_idf': self.smooth_idf,
            'documents': [dict(document) for document in self.documents],
            'document_frequency': dict(self.document_frequency)
        }

        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix='.tfidf_',
            suffix='.tmp',
            dir=destination_dir
        )

        try:
            with os.fdopen(file_descriptor, 'wb') as output_file:
                pickle.dump(payload, output_file, protocol=pickle.HIGHEST_PROTOCOL)

            os.replace(temporary_path, file_path)

        except Exception:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
            raise

    @classmethod
    def load(cls, file_path):
        """
        Load a modern TF-IDF index.

        Old tuple-only pickle files cannot be safely incrementally updated
        because they lack original per-document term counts.
        """
        if not os.path.isfile(file_path):
            raise IOError('Previous index does not exist: {0}'.format(file_path))

        with open(file_path, 'rb') as input_file:
            payload = pickle.load(input_file)

        if isinstance(payload, tuple):
            raise ValueError(
                'This is a legacy TF-IDF pickle containing only final values. '
                'It cannot be safely updated because the original document '
                'term counts were not saved. Rebuild it once with this version.'
            )

        if not isinstance(payload, dict):
            raise ValueError('Invalid TF-IDF index format.')

        if payload.get('format') != cls.FORMAT_NAME:
            raise ValueError('Unsupported TF-IDF index format.')

        index = cls(
            lowercase=payload.get('lowercase', False),
            smooth_idf=payload.get('smooth_idf', True)
        )

        index.documents = [
            Counter(document)
            for document in payload.get('documents', [])
        ]

        index.document_frequency = Counter(
            payload.get('document_frequency', {})
        )

        return index


# ---------------------------------------------------------------------------
# Backwards-friendly public function
# ---------------------------------------------------------------------------

def find_tf_idf(file_names=None, prev_file_path=None, dump_path=None,
                lowercase=False, smooth_idf=True, encoding='utf-8'):
    """
    Create or update a TF-IDF index from one or more text files.

    Every non-empty line is treated as one document.

    Args:
        file_names: list of text-file paths.
        prev_file_path: saved .tfidfpkl index to extend.
        dump_path: destination .tfidfpkl path.
        lowercase: normalise tokens to lowercase.
        smooth_idf: use stable smoothed IDF values.
        encoding: input file encoding.

    Returns:
        tuple:
            document_frequency_dict,
            list_of_tfidf_document_dicts
    """
    if file_names is None:
        file_names = []

    if isinstance(file_names, str):
        file_names = [file_names]

    if prev_file_path:
        print(TAG, 'Loading existing index from', prev_file_path)
        index = TfidfIndex.load(prev_file_path)
        previous_document_count = index.document_count
        previous_unique_terms = len(index.document_frequency)
    else:
        index = TfidfIndex(
            lowercase=lowercase,
            smooth_idf=smooth_idf
        )
        previous_document_count = 0
        previous_unique_terms = 0

    added_documents = index.add_files(file_names, encoding=encoding)

    idf, tf_idf = index.export_legacy_style()

    print(
        TAG,
        'Unique terms:',
        len(idf),
        paint(
            '( +{0} )'.format(len(idf) - previous_unique_terms),
            'g'
        )
    )

    print(
        TAG,
        'Documents:',
        index.document_count,
        paint(
            '( +{0} )'.format(index.document_count - previous_document_count),
            'g'
        )
    )

    if dump_path:
        index.save(dump_path)
        print(TAG, 'Saved index to', dump_path)

    if added_documents == 0:
        print(TAG, paint('Warning: no non-empty documents were added.', 'y'))

    return idf, tf_idf


# ---------------------------------------------------------------------------
# Command-line usage
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generate or update TF-IDF vectors from line-based documents.'
    )

    parser.add_argument(
        'files',
        nargs='+',
        help='Text files where every non-empty line represents one document.'
    )

    parser.add_argument(
        '--dump',
        required=True,
        help='Output .tfidfpkl index path.'
    )

    parser.add_argument(
        '--append',
        dest='previous_index',
        help='Existing modern .tfidfpkl index to extend.'
    )

    parser.add_argument(
        '--lowercase',
        action='store_true',
        help='Convert all tokens to lowercase before processing.'
    )

    parser.add_argument(
        '--no-smoothing',
        action='store_true',
        help='Use classic unsmoothed log(N / df) IDF.'
    )

    parser.add_argument(
        '--encoding',
        default='utf-8',
        help='Input encoding. Default: utf-8'
    )

    args = parser.parse_args()

    find_tf_idf(
        file_names=args.files,
        prev_file_path=args.previous_index,
        dump_path=args.dump,
        lowercase=args.lowercase,
        smooth_idf=not args.no_smoothing,
        encoding=args.encoding
    )


if __name__ == '__main__':
    main()
