import unittest

import numpy as np

from experiments.cloud_belief.belief_filter import (
    VISION_MODEL_ON_COMMONS_PHOTOS,
    belief_entropy_bits,
    most_uncertain,
    relaxed_beliefs,
    updated_beliefs,
)


class RelaxedBeliefsTest(unittest.TestCase):
    priors = np.array([0.01, 0.2])
    beliefs = np.array([0.9, 0.001])

    def test_no_elapsed_time_keeps_beliefs(self) -> None:
        relaxed = relaxed_beliefs(self.beliefs, self.priors, 60, 0)
        np.testing.assert_allclose(relaxed, self.beliefs)

    def test_long_gap_returns_to_prior(self) -> None:
        relaxed = relaxed_beliefs(self.beliefs, self.priors, 60, 10_000)
        np.testing.assert_allclose(relaxed, self.priors)

    def test_belief_moves_monotonically_towards_prior(self) -> None:
        sooner = relaxed_beliefs(self.beliefs, self.priors, 60, 10)
        later = relaxed_beliefs(self.beliefs, self.priors, 60, 30)
        self.assertTrue(self.beliefs[0] > sooner[0] > later[0] > self.priors[0])
        self.assertTrue(self.beliefs[1] < sooner[1] < later[1] < self.priors[1])

    def test_matches_exact_two_state_chain_after_one_mean_duration(self) -> None:
        prior = np.array([0.5])
        relaxed = relaxed_beliefs(np.array([1.0]), prior, 60, 60)
        self.assertAlmostEqual(relaxed[0], 0.5 + 0.5 * np.exp(-2))


class UpdatedBeliefsTest(unittest.TestCase):
    def test_zero_evidence_keeps_beliefs(self) -> None:
        beliefs = np.array([0.02, 0.7])
        np.testing.assert_allclose(updated_beliefs(beliefs, np.zeros(2)), beliefs)

    def test_update_multiplies_odds_by_likelihood_ratio(self) -> None:
        updated = updated_beliefs(np.array([0.2]), np.log(np.array([8.0])))
        self.assertAlmostEqual(updated[0], 2 / 3)

    def test_measured_table_orders_observations_by_evidence(self) -> None:
        ratios = [
            VISION_MODEL_ON_COMMONS_PHOTOS.log_likelihood_ratio(observation)
            for observation in VISION_MODEL_ON_COMMONS_PHOTOS.given_present
        ]
        self.assertEqual(ratios, sorted(ratios))
        self.assertLess(ratios[0], 0)
        self.assertGreater(ratios[-1], 0)

    def test_measured_table_rows_are_distributions(self) -> None:
        model = VISION_MODEL_ON_COMMONS_PHOTOS
        self.assertAlmostEqual(sum(model.given_present.values()), 1)
        self.assertAlmostEqual(sum(model.given_absent.values()), 1)


class MostUncertainTest(unittest.TestCase):
    def test_entropy_is_symmetric_and_peaks_at_half(self) -> None:
        entropy = belief_entropy_bits(np.array([0.1, 0.9, 0.5]))
        self.assertAlmostEqual(entropy[0], entropy[1])
        self.assertAlmostEqual(entropy[2], 1)

    def test_selects_beliefs_nearest_half(self) -> None:
        beliefs = np.array([0.001, 0.4, 0.99, 0.6, 0.05])
        self.assertEqual(set(most_uncertain(beliefs, 2).tolist()), {1, 3})


if __name__ == "__main__":
    unittest.main()
