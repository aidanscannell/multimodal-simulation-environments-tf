import cv2
import numpy as np
import scipy as sp
from tf_agents.environments import (
    py_environment,
    tf_environment,
    tf_py_environment,
    utils,
)
from tf_agents.specs import array_spec
from tf_agents.trajectories import time_step as ts

float_type = np.float64

# control constraints
MIN_VELOCITY = -10
MAX_VELOCITY = 10
MIN_ACCELERATION = -10
MAX_ACCELERATION = 10
MIN_ACTION = MIN_VELOCITY
MAX_ACTION = MAX_VELOCITY

# state constraints (domain)
MIN_STATE = -3.0
MAX_STATE = 3.0

# environment parameters
LOW_PROCESS_NOISE_VAR = np.array([0.000001, 0.000002])
HIGH_PROCESS_NOISE_VAR = np.array([0.0001, 0.00004])
BITMAP_RESOLUTION = 600  # if gating_bitmap=None then use np.ones(600)
GATING_BITMAP = None

# simulation parameters
DELTA_TIME = 0.05
VELOCITY_INIT = 0.0


# TODO before using for RL must have episode termination condition
#      that sets self._episode_ended = True
class VelocityControlledQuadcopter2DEnv(py_environment.PyEnvironment):
    def __init__(
        self,
        min_observation=MIN_STATE,
        max_observation=MAX_STATE,
        min_action=MIN_VELOCITY,
        max_action=MAX_VELOCITY,
        low_process_noise_var=LOW_PROCESS_NOISE_VAR,
        high_process_noise_var=HIGH_PROCESS_NOISE_VAR,
        gating_bitmap=None,
        velocity_init=0.0,
        delta_time=DELTA_TIME,
        min_acceleration=MIN_ACCELERATION,
        max_acceleration=MAX_ACCELERATION,
    ):
        # velocity controlled so num_states=num_actions=num_dims
        num_dims = 2
        num_states = num_dims
        num_actions = num_dims

        # simulation parameters
        self.state_init = np.zeros([num_dims], dtype=float_type)
        self._state = self.state_init
        self.delta_time = delta_time
        self.previous_velocity = velocity_init

        # environment parameters
        if isinstance(low_process_noise_var, np.ndarray):
            self.low_process_noise_var = low_process_noise_var
        else:
            print("low_process_noise_var isn't array so broadcasting")
            self.low_process_noise_var = low_process_noise_var * np.ones(num_states)
        if isinstance(high_process_noise_var, np.ndarray):
            self.high_process_noise_var = high_process_noise_var
        else:
            print("high_process_noise_var isn't array so broadcasting")
            self.high_process_noise_var = high_process_noise_var * np.ones(num_states)

        # configure action spec
        if not isinstance(min_action, np.ndarray):
            min_action = min_action * np.ones(num_actions)
            print("min_action isn't array so broadcasting")
        if not isinstance(max_action, np.ndarray):
            max_action = max_action * np.ones(num_actions)
            print("max_action isn't array so broadcasting")
        self._action_spec = array_spec.BoundedArraySpec(
            shape=(1, num_actions),
            dtype=float_type,
            minimum=min_action,
            maximum=max_action,
            name="action",
        )
        # configure observation spec
        if not isinstance(min_observation, np.ndarray):
            min_observation = min_observation * np.ones(num_states)
            print("min_observation isn't array so broadcasting")
        if not isinstance(max_observation, np.ndarray):
            max_observation = max_observation * np.ones(num_states)
            print("max_observation isn't array so broadcasting")
        self._observation_spec = array_spec.BoundedArraySpec(
            shape=(1, num_states),
            dtype=float_type,
            minimum=min_observation,
            maximum=max_observation,
            name="observation",
        )
        self.episode_ended = False

        if gating_bitmap is None:
            resolution = BITMAP_RESOLUTION
            self.gating_bitmap = np.ones([resolution, resolution])
        elif isinstance(gating_bitmap, str):
            self.gating_bitmap = cv2.imread(gating_bitmap, cv2.IMREAD_GRAYSCALE)
            self.gating_bitmap = self.gating_bitmap / 255
        elif isinstance(gating_bitmap, np.ndarray):
            self.gating_bitmap = gating_bitmap
        else:
            raise ("gating_bitmap must be np.ndarray or filepath string for bitmap")
        # TODO check x and y are the right way around
        self.num_pixels = np.array(
            # [self.gating_bitmap.shape[0] - 1, self.gating_bitmap.shape[1] - 1]
            [self.gating_bitmap.shape[1] - 1, self.gating_bitmap.shape[0] - 1]
        )

    def state_to_pixel(self, state):
        """Returns the bitmap pixel index associated with state"""
        if len(state.shape) == 1:
            state = state.reshape(1, -1)
        pixel = (
            (state[0, :] - self.observation_spec().minimum)
            / (self.observation_spec().maximum - self.observation_spec().minimum)
            * self.num_pixels
        )
        pixel = np.array([-pixel[1], pixel[0]])
        return np.rint(pixel).astype(int)

    def action_spec(self):
        return self._action_spec

    def observation_spec(self):
        return self._observation_spec

    def reset(self, state_init=None):
        """Return initial_time_step."""
        self._current_time_step = self._reset(state_init)
        return self._current_time_step

    def _reset(self, state=None):
        # print("Reseting environment")
        if state is None:
            self._state = self.state_init
        else:
            self._state = state
        self._episode_ended = False
        return ts.restart(np.array([self._state], dtype=float_type))

    def _step(self, action):
        delta_state = self.transition_dynamics(self._state, action)
        # print("delta state")
        # print(delta_state)
        self._state += delta_state
        reward = 0
        # self._episode_ended = True  # remove this when term conds added
        if self._episode_ended:
            return ts.termination(np.array([self._state], dtype=float_type), reward)
        else:
            return ts.transition(
                np.array([self._state], dtype=float_type),
                reward=reward,
                discount=1.0,
            )

    def _process_noise(self, state):
        mean = np.array([0.0, 0.0])
        pixel = self.state_to_pixel(state)
        gating_value = self.gating_bitmap[pixel[0], pixel[1]]
        if gating_value == 1.0:
            var = self.low_process_noise_var
        else:
            var = self.high_process_noise_var
        cov = np.diag(var)
        noise = sp.random.multivariate_normal(mean, cov)
        return noise

    def transition_dynamics(self, state, action):
        velocity = action  # as veloctiy controlled

        delta_state_deterministic = (
            0.5 * (self.previous_velocity + velocity) * self.delta_time
        )  # internal dynamics (suvat)
        process_noise = self._process_noise(state)  # external dynamics
        # print("process_noise")
        # print(process_noise)
        delta_state = delta_state_deterministic + process_noise
        # delta_state = delta_state_deterministic

        self.previous_velocity = velocity
        return delta_state


def test_VelocityControlledQuadcopter2DEnv():
    env = VelocityControlledQuadcopter2DEnv()
    utils.validate_py_environment(env, episodes=2)


def test_tf_env(env):
    tf_env = tf_py_environment.TFPyEnvironment(env)

    print(
        "Valid tf Environment? ",
        isinstance(tf_env, tf_environment.TFEnvironment),
    )
    print("TimeStep Specs:\n", tf_env.time_step_spec())
    print("Action Specs:\n", tf_env.action_spec())


if __name__ == "__main__":
    test_VelocityControlledQuadcopter2DEnv()

    env = VelocityControlledQuadcopter2DEnv()
    test_tf_env(env)
