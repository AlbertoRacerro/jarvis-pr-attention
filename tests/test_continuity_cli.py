import unittest

from pr_attention.continuity_cli import build_parser


class ContinuityCliTests(unittest.TestCase):
    def test_all_v11_commands_are_parseable(self):
        parser = build_parser()
        cases = [
            (["checkpoint", "source.json"], "checkpoint"),
            (["packet", "o/r", "7", "source.json"], "packet"),
            (["digest", "packet.json"], "digest"),
            (["template", "packet.json", "--reviewer-name", "r"], "template"),
            (["envelope", "packet.json", "--reviewer-name", "r"], "envelope"),
            (["validate", "packet.json", "result.json"], "validate"),
            (["gate", "snapshot.json", "validation.json"], "gate"),
        ]
        for argv, expected in cases:
            with self.subTest(command=expected):
                self.assertEqual(parser.parse_args(argv).command, expected)

    def test_packet_exposes_thread_and_patch_budgets(self):
        args = build_parser().parse_args(
            [
                "packet",
                "o/r",
                "7",
                "source.json",
                "--max-total-patch-bytes",
                "100",
                "--max-file-patch-bytes",
                "50",
                "--max-thread-bytes",
                "20",
                "--max-total-thread-bytes",
                "40",
                "--max-threads",
                "3",
            ]
        )
        self.assertEqual(args.max_total_patch_bytes, 100)
        self.assertEqual(args.max_file_patch_bytes, 50)
        self.assertEqual(args.max_thread_bytes, 20)
        self.assertEqual(args.max_total_thread_bytes, 40)
        self.assertEqual(args.max_threads, 3)


if __name__ == "__main__":
    unittest.main()
