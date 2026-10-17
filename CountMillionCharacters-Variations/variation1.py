                counts[c] = counts.get(c, 0) + 1
        return counts

    def test_original_api_and_default_semantics(self):
        cases = ["", "Aaa b\nB!", "Straße Ωμέγα 😀", "e\u0301 é\t123\r\nX\rY", "\ufeffBOM"]
        for i, value in enumerate(cases):
            file = self.write(f"case{i}.txt", value)
            with self.subTest(case=i):
                self.assertEqual(count_chars(str(file)), self.original(file))
                for size in [1, 2, 3, 7, 65536]:
                    r = analyze_file(file, Settings(chunk_size=size))
                    self.assertEqual(dict(r.counts), self.original(file))

    def test_long_random_file_and_ngram_boundary(self):
        rng = random.Random(42)
        text = "".join(rng.choices("ABC def\n123ßΩ☁️", k=16000))
        file = self.write("random.txt", text)
        for n in [1, 2, 3, 5, 8]:
            expected_text = text.upper()
            expected = Counter(expected_text[i:i+n] for i in range(len(expected_text)-n+1))
            for size in [1, 2, 9, 128, 1024]:
                with self.subTest(n=n, size=size):
                    actual = analyze_file(file, Settings(ngram=n, chunk_size=size))
                    self.assertEqual(actual.counts, expected)

    def test_line_word_metadata_and_empty(self):
        cases = ["", "one two", "a\nb\n", "\n\n", "\n a  b\tfoo\n bar", "αβγ\r\nδεζ"]
        for i, text in enumerate(cases):
            f = self.write(f"meta{i}.txt", text)
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            for size in [1, 2, 9]:
                with self.subTest(i=i, size=size):
                    result = analyze_file(f, Settings(chunk_size=size))
                    self.assertEqual(result.words, len(normalized.split()))
                    self.assertEqual(result.lines, len(normalized.splitlines()))

    def test_filters_and_export(self):
        file = self.write("filter.txt", "a A a! 1\n")
        result = analyze_file(file, Settings(ignore_whitespace=True, ignore_digits=True, ignore_punctuation=True))
        self.assertEqual(dict(result.counts), {"A": 3})
        json_export = json.loads(render_json([result], "frequency", 0))
        self.assertEqual(json_export["analyses"][0]["frequencies"][0]["unicode_codepoint"], "U+0041")
        csv_export = list(csv.DictReader(io.StringIO(render_csv([result], "frequency", 0))))
        self.assertEqual(csv_export[0]["count"], "3")

    def test_normalization_and_auto_encoding(self):
        path = self.write("decomposed.txt", "e\u0301 é")
        result = analyze_file(path, Settings(normalize="NFC", chunk_size=1))
        self.assertEqual(result.counts, Counter("É É"))
        path16 = self.write("utf16.txt", "hi Ω!", encoding="utf-16")
        result16 = analyze_file(path16, Settings(encoding="auto"))
        self.assertEqual(result16.counts, Counter("HI Ω!"))

    def test_directories_and_aggregate(self):
        one = self.write("a.txt", "abc")
        two = self.write("sub/b.txt", "def")
        paths, errors = expand_paths([str(self.root)], recursive=True)
        self.assertEqual(set(paths), {one, two})
        self.assertFalse(errors)
        result = aggregate([analyze_file(p, Settings()) for p in paths])
        self.assertEqual(result.counts, Counter("ABCDEF"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
