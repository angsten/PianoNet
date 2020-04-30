import numpy as np

from pianonet.core.pianoroll import Pianoroll


class NoteArray(object):
    """
    A NoteArray is a 1D stream of piano note states derived from flattening a pianoroll. The notearray is useful
    for training a 1D convolutional neural net. The parent pianoroll can be set to lower resolution before flattening.
    Also, most keys in pianorolls are always or nearly always zero, usually the highest and lowest keys. This is why
    cropping high and low keys of the input pianoroll is supported.

    Example array:

    timestep = 0                 timestep = 1
     A  A# B  C  C# D  D# E  ... A  A# B  C  C# D  D# E  ...
    [0, 0, 0, 1, 0, 0, 0, 0, ... 1, 0, 0, 1, 0, 0, 0, 0, ...]
    """

    def __init__(self, pianoroll=None, flat_array=None, min_key_index=0, num_keys=128, resolution=1.0):
        """
        pianoroll: Instance of Pianoroll class used to populate the notearray's array
        flat_array: Optionally can initialize from a 1D array of note states. **This 1D array is assumed to already
                    be cropped and downsampled at the specified parameters given to this constructor**
        min_key_index: array index of the lowest piano key to not crop
        num_keys: number of piano keys in pianoroll to keep. min_key_index + num_keys - 1 gives the index of the highest
                  included key.
        resolution: Float between 0 and 1 controlling how much to downsample the original pianoroll array.
                    resolution=0.5 means every other note is sampled. Must be 1.0 if a flat_array is given
        """

        if (pianoroll != None) and isinstance(flat_array, np.ndarray):
            raise Exception("Cannot use both a pianoroll and flat_array initializer. Choose one.")

        if (min_key_index + num_keys) > 128:
            raise Exception(
                "(min_key_index + num_keys) = " + str(min_key_index + num_keys) + ", which is greater than 128")

        if resolution > 1.0:
            raise Exception("Provided resolution of " + str(resolution) + " is greater than 1.0.")

        self.min_key_index = min_key_index
        self.num_keys = num_keys
        self.resolution = resolution

        if isinstance(flat_array, np.ndarray):
            if (flat_array.shape[0] % num_keys) != 0:
                raise Exception("flat_array contains a timestep with a partial key state. This is not allowed.")

            self.time_steps = (flat_array.shape[0] // num_keys)
            self.array = flat_array.copy()
        else:
            pianoroll = pianoroll.get_copy()

            if self.resolution != 1.0:
                pianoroll.stretch(stretch_fraction=resolution)

            self.time_steps = pianoroll.array.shape[0]

            cropped_pianoroll = pianoroll.array[:, min_key_index:(min_key_index + num_keys)]

            self.array = cropped_pianoroll.flatten()

    def get_pianoroll(self):
        """
        Recover the original pianoroll as high of fidelity as possible given the initial down-sampling and cropping.
        A Pianoroll instance is returned.
        """

        cropped_unflattened_pianoroll_array = np.reshape(self.array, (self.time_steps, self.num_keys))

        unflattened_pianoroll_array = np.zeros((self.time_steps, 128)).astype('bool')

        unflattened_pianoroll_array[:,
        self.min_key_index:self.min_key_index + self.num_keys] = cropped_unflattened_pianoroll_array

        pianoroll_low_resolution = Pianoroll(unflattened_pianoroll_array)

        if self.resolution == 1.0:
            return pianoroll_low_resolution
        else:
            return pianoroll_low_resolution.get_stretched(stretch_fraction=(1.0 / self.resolution))

    def get_length_in_notes(self):
        """
        Returns as an integer the length of the stored 1D array
        """

        return self.array.shape[0]

    def get_length_in_timesteps(self):
        """
        Returns as an integer the length of the note array in timesteps
        """

        return (self.get_length_in_notes()//self.num_keys)