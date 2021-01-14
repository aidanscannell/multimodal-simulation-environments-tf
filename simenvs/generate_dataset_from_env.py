import cv2
import jax
import jax.numpy as jnp
import numpy as np

from simenvs.quadcopter_sim import VelocityControlledQuadcopter2DEnv

float_type = np.float64

# control constraints
MIN_VELOCITY = -10
MAX_VELOCITY = 10
MIN_ACCELERATION = -10
MAX_ACCELERATION = 10
MIN_ACTION = MIN_VELOCITY
MAX_ACTION = MAX_VELOCITY

# observation constraints
MIN_OBSERVATION = -3
MAX_OBSERVATION = 3

VELOCITY_INIT = 0.0
DELTA_TIME = 0.1

NUM_PIXELS = np.array([600 - 1, 600 - 1])


def gen_dummy_states(
    num_dims,
    min_observation=MIN_OBSERVATION,
    max_observation=MAX_OBSERVATION,
    num_data_per_dim=10,
):
    states = []

    # # create a uniform grid of states
    # for _ in range(num_dims):
    #     states.append(
    #         np.linspace(
    #             min_observation, max_observation, num_data_per_dim
    #         ).reshape(-1)
    #     )

    # states_grid = np.stack(states, -1)
    # states_x, states_y = np.meshgrid(states_grid[:, 0], states_grid[:, 1])
    # states_grid = np.concatenate(
    #     [states_x.reshape(-1, 1), states_y.reshape(-1, 1)], -1
    # )

    # get some randome (out of grid) states as well
    states = np.random.uniform(
        min_observation * np.ones(num_dims),
        max_observation * np.ones(num_dims),
        (num_data_per_dim, num_dims),
    )
    # states = np.concatenate([states, states_grid], 0)
    return states


def gen_dummy_actions(
    num_dims, min_action=MIN_ACTION, max_action=MAX_ACTION, num_data_per_dim=10
):
    actions = []
    for _ in range(num_dims):
        actions.append(
            np.linspace(min_action, max_action, num_data_per_dim).reshape(-1)
        )
    actions = np.stack(actions, -1)
    return actions


# @jax.jit
def create_state_action_inputs(num_dims, states, actions):
    # states_x, states_y = np.meshgrid(states[:, 0], states[:, 1])
    # states = np.concatenate(
    #     [states_x.reshape(-1, 1), states_y.reshape(-1, 1)], -1
    # )
    # print("All combinations of states: ", states.shape)

    actions_x, actions_y = np.meshgrid(actions[:, 0], actions[:, 1])
    actions = np.concatenate(
        [actions_x.reshape(-1, 1), actions_y.reshape(-1, 1)], -1
    )
    print("All combindations of actions: ", actions.shape)

    def grid_action(action):
        action = action.reshape(1, -1)
        num_test = states.shape[0]
        actions_x, actions_y = np.meshgrid(states[:, 0], states[:, 1])
        actions = np.concatenate(
            [actions_x.reshape(-1, 1), actions_y.reshape(-1, 1)], -1
        )
        action_broadcast = jnp.tile(action, (num_test, 1))
        state_action = jnp.concatenate([states, action_broadcast], -1)
        return state_action

    states_actions = jax.vmap(grid_action, in_axes=0)(actions)
    state_action_inputs = states_actions.reshape(-1, 2 * num_dims)
    return state_action_inputs


def transition_dynamics(state_action, env):
    state_action = state_action.reshape(1, -1)
    num_dims = int(state_action.shape[1] / 2)
    state = state_action[:, :num_dims]
    action = state_action[:, num_dims:]

    env.reset(state)  # set environment to state in state_action

    # next_time_step = env.step(action)
    delta_state = env.transition_dynamics(state, action)
    return delta_state.reshape(-1)
    # next_state = next_time_step.observation
    # return next_state.reshape(-1)


def state_to_pixel(state, env):
    if len(state.shape) == 1:
        state = state.reshape(1, -1)
    pixel = (
        (state[0, :] - env.observation_spec().minimum)
        / (env.observation_spec().maximum - env.observation_spec().minimum)
        * NUM_PIXELS
    )
    # pixel *= np.array([-1, 1])
    return np.rint(pixel).astype(int)


def generate_transitions_dataset(
    gating_bitmap,
    omit_data_mask=None,
    num_data_per_dim=10,
    num_actions_per_dim=4,
):
    num_dims = 2
    env = VelocityControlledQuadcopter2DEnv(gating_bitmap=gating_bitmap)

    states = gen_dummy_states(num_dims, num_data_per_dim=num_data_per_dim)
    print("Initial states shape: ", states.shape)

    actions = gen_dummy_actions(num_dims, num_data_per_dim=num_actions_per_dim)
    print("Initial actions shape: ", actions.shape)
    state_action_inputs = create_state_action_inputs(num_dims, states, actions)
    print("State action inputs shape: ", state_action_inputs.shape)
    # print(state_action_inputs)

    num_data = state_action_inputs.shape[0]
    delta_state_outputs = []
    for row in range(num_data):
        delta_state = transition_dynamics(state_action_inputs[row, :], env)
        delta_state_outputs.append(delta_state)
    delta_state_outputs = np.stack(delta_state_outputs)

    print("Delta state outputs: ", delta_state_outputs.shape)
    return state_action_inputs, delta_state_outputs


def apply_mask_to_states(states, env, omit_data_mask=None):
    if isinstance(omit_data_mask, str):
        omit_data_mask = cv2.imread(omit_data_mask, cv2.IMREAD_GRAYSCALE)
        # cv2.imshow('GFG', omit_data_mask)
        omit_data_mask = omit_data_mask / 255
    elif isinstance(omit_data_mask, np.ndarray):
        omit_data_mask = omit_data_mask
    else:
        raise (
            "omit_data_mask must be np.ndarray or filepath string for bitmap"
        )

    rows_to_delete = []
    for row in range(states.shape[0]):
        pixel = env.state_to_pixel(states[row, :])
        if omit_data_mask[pixel[0], pixel[1]] < 0.5:
            rows_to_delete.append(row)

    states = np.delete(states, rows_to_delete, 0)
    return states


def generate_transitions_dataset_const_action(
    action, gating_bitmap, omit_data_mask=None, num_states=10
):
    num_dims = 2
    env = VelocityControlledQuadcopter2DEnv(gating_bitmap=gating_bitmap)

    states = gen_dummy_states(num_dims, num_data_per_dim=num_data_per_dim)
    print("Initial states shape: ", states.shape)
    states = apply_mask_to_states(states, env, omit_data_mask)
    print("Initial states shape after applying mask: ", states.shape)

    print("Initial action shape: ", action.shape)
    if len(action.shape) == 1:
        action = action.reshape(1, -1)
    state_action_inputs = create_state_action_inputs(num_dims, states, action)
    print("State action inputs shape: ", state_action_inputs.shape)
    # print(state_action_inputs)

    num_data = state_action_inputs.shape[0]
    delta_state_outputs = []
    for row in range(num_data):
        delta_state = transition_dynamics(state_action_inputs[row, :], env)
        delta_state_outputs.append(delta_state)
    delta_state_outputs = np.stack(delta_state_outputs)

    print("Delta state outputs: ", delta_state_outputs.shape)
    return state_action_inputs, delta_state_outputs


# def generate_transitions_dataset_const_action(action):
#     num_data_per_dim = 10
#     num_actions_per_dim = 4
#     state_action_inputs, delta_state_outputs = generate_transitions_dataset(
#         num_data_per_dim=num_data_per_dim,
#         num_actions_per_dim=num_actions_per_dim,
#     )
#     np.savez(
#         "./data/quad_sim_data_new.npz",
#         x=state_action_inputs,
#         y=delta_state_outputs,
#     )


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    num_data_per_dim = 40
    num_actions_per_dim = 1
    save_dataset_filename = "./data/quad_sim_data_constant_action.npz"
    gating_bitmap = "./gating_network.bmp"

    state_action_inputs, delta_state_outputs = generate_transitions_dataset(
        gating_bitmap,
        num_data_per_dim=num_data_per_dim,
        num_actions_per_dim=num_actions_per_dim,
    )
    np.savez(
        save_dataset_filename,
        x=state_action_inputs,
        y=delta_state_outputs,
    )

    plt.quiver(
        state_action_inputs[:, 0],
        state_action_inputs[:, 1],
        delta_state_outputs[:, 0],
        delta_state_outputs[:, 1],
    )
    plt.show()