import os
import pickle
import subprocess

from tensorflow.keras.callbacks import ModelCheckpoint
from tensorflow.keras.models import load_model
from tensorflow.keras.optimizers import Adam

from pianonet.core.misc_tools import save_dictionary_to_json_file, load_dictionary_from_json_file
from pianonet.model_building.get_model_input_shape import get_model_input_shape
from pianonet.training_utils.custom_keras_callbacks import ExecuteEveryNBatchesCallback
from pianonet.training_utils.logger import Logger
from pianonet.training_utils.master_note_array import MasterNoteArray
from pianonet.training_utils.note_sample_generator import NoteSampleGenerator


class Run(Logger):
    """
    Wrapper for a single model training run with set parameters denoted by a dictionary saved to file. Every
    run sits in its own directory, which at minimum must contain a run_description.json file describing
    where to find the data, how to generate or find the initial model, and how to train the model.
    """

    def __init__(self, path):
        """
        path: Directory in which the run is executed.
        """

        self.path = os.path.abspath(path)
        super().__init__(logger_name=__name__, log_file_path=self.get_full_path_from_run_file_name('output.log'))

        for i in range(0, 3): self.log()
        self.log("*-" * 60)
        self.log("*-" * 60)
        self.log("*-*-*-* BEGINNING RUN AT " + self.path)
        self.log("*-" * 60)
        self.log("*-" * 60)
        for i in range(0, 3): self.log()

        run_description = load_dictionary_from_json_file(json_file_path=self.get_run_description_path())

        if os.path.exists(self.get_state_path()):
            self.log("Saved state found. Restarting the run and incrementing the run index.")
            self.load_state()
            self.state['run_index'] += 1

            previous_model_path = self.get_previous_run_index_prefixed_path('trained.model')
            self.log("Using previous model at " + previous_model_path)
            run_description['model_description']['model_path'] = previous_model_path
            del run_description['model_description']['model_initializer']

        else:
            self.log("No previously saved state found. Starting as a new run.")
            self.state = {
                'run_index': 0,
                'status': 'running',
            }

        self.log("State of run before execution is: ")
        self.log(self.state)

        self.execute(run_description)

    def get_state_path(self):
        """
        Returns path within the run directory where the state data is stored.
        """

        return os.path.join(self.path, 'state.json')

    def get_run_description_path(self):
        return os.path.join(self.path, 'run_description.json')

    def save_state(self):
        """
        Save this instance's current state to file.
        """

        save_dictionary_to_json_file(dictionary=self.state, json_file_path=self.get_state_path())

    def load_state(self):
        """
        Loads the state from the state file into this run's state.
        """

        self.state = load_dictionary_from_json_file(json_file_path=self.get_state_path())

    def get_run_index(self):
        return self.state['run_index']

    def get_status(self):
        return self.state['status']

    def get_full_path_from_run_file_name(self, file_name):
        return os.path.join(self.path, file_name)

    def get_index_prepended_file_base_name(self, index, file_base_name):
        return str(index) + "_" + file_base_name

    def get_previous_run_index_prefixed_path(self, file_base_name):
        return self.get_full_path_from_run_file_name(
            self.get_index_prepended_file_base_name(
                index=self.get_run_index() - 1,
                file_base_name=file_base_name,
            )
        )

    def get_run_index_prefixed_path(self, file_base_name):
        return self.get_full_path_from_run_file_name(
            self.get_index_prepended_file_base_name(
                index=self.get_run_index(),
                file_base_name=file_base_name,
            )
        )

    def fetch_model(self, model_description):
        self.log()
        if (model_description['model_path'] == "") and ('model_initializer' in model_description):
            model_initializer = model_description['model_initializer']
            self.log("Initializing model using file at " + model_initializer['path'])
            self.log("Params used for model initialization are " + str(model_initializer['params']))

            model_output_path = self.get_run_index_prefixed_path("initial.model")
            model_parameters_file_path = self.get_full_path_from_run_file_name('model_parameters')

            with open(model_parameters_file_path, 'wb') as file:
                pickle.dump(model_initializer['params'], file)

            model_creation_command = "python " + model_initializer[
                'path'] + " " + model_parameters_file_path + " " + model_output_path
            self.log("\nCalling model creator with command:")
            self.log(model_creation_command)

            subprocess.run(model_creation_command, shell=True, check=True)

            os.remove(model_parameters_file_path)

            self.model = load_model(model_output_path)

        elif model_description['model_path'] != "":
            self.log("Loading model at " + model_description['model_path'])

            self.model = load_model(model_description['model_path'])
        else:
            raise Exception("No method of creating or loading the model has been specified in the run description.")

        self.log()

        num_notes_in_model_input = get_model_input_shape(self.model)
        time_steps_receptive_field = num_notes_in_model_input / self.note_array_transformer.num_keys

        self.log("Number of notes in model input: " + str(num_notes_in_model_input))
        self.log("Time steps in receptive field: " + str(time_steps_receptive_field))
        self.log("Seconds in receptive field: " + str(round((time_steps_receptive_field) / 48, 2)))
        self.log()
        self.model.summary(print_fn=self.log)
        self.log()

    def fetch_data(self, data_description):
        self.log()
        self.log("Loading training master note array from " + data_description['training_master_note_array_path'])
        self.training_master_note_array = MasterNoteArray(file_path=data_description['training_master_note_array_path'])
        self.note_array_transformer = self.training_master_note_array.note_array_transformer
        self.num_keys = self.note_array_transformer.num_keys

        self.log("Loading validation master note array from " + data_description['validation_master_note_array_path'])
        self.validation_master_note_array = MasterNoteArray(
            file_path=data_description['validation_master_note_array_path'])

    def checkpoint_method_creator(self, training_note_sample_generator):
        def checkpoint_method():
            self.save_state()
            self.model.save(self.get_run_index_prefixed_path('trained.model'))

            generator_checkpoint_path = self.get_run_index_prefixed_path('generator_state.gs')
            training_note_sample_generator.save_state(generator_checkpoint_path)

        return checkpoint_method

    def execute(self, run_description):
        """
        Begins a model training session following the specifications in the provided run_description.

        run_description: Dictionary specifying how the model training session should be carried out.
        """

        self.log()
        self.log("Executing run description:")
        self.log(run_description)

        save_dictionary_to_json_file(
            dictionary=run_description,
            json_file_path=self.get_run_index_prefixed_path('run_desciption.json')
        )

        self.fetch_data(data_description=run_description['data_description'])
        self.fetch_model(model_description=run_description['model_description'])

        training_description = run_description['training_description']
        training_batch_size = training_description['batch_size']
        num_predicted_notes_in_training_sample = self.num_keys * training_description[
            'num_predicted_time_steps_in_sample']

        num_notes_in_model_input = get_model_input_shape(self.model)

        training_note_sample_generator = NoteSampleGenerator(
            master_note_array=self.training_master_note_array,
            num_notes_in_model_input=num_notes_in_model_input,
            num_predicted_notes_in_sample=num_predicted_notes_in_training_sample,
            batch_size=training_batch_size,
            random_seed=0)

        validation_description = run_description['validation_description']
        validation_batch_size = validation_description['batch_size']
        num_predicted_notes_in_validation_sample = self.num_keys * validation_description[
            'num_predicted_time_steps_in_sample']

        validation_note_sample_generator = NoteSampleGenerator(
            master_note_array=self.validation_master_note_array,
            num_notes_in_model_input=num_notes_in_model_input,
            num_predicted_notes_in_sample=num_predicted_notes_in_validation_sample,
            batch_size=validation_batch_size,
            random_seed=0)

        if self.get_run_index() != 0:
            generator_checkpoint_path = self.get_previous_run_index_prefixed_path('generator_state.gs')
            training_note_sample_generator.load_state(file_path=generator_checkpoint_path)

        self.log('\n' + training_note_sample_generator.get_summary_string())

        optimizer_description = training_description['optimizer_description']

        if optimizer_description['type'] == 'Adam':
            optimizer = Adam(**optimizer_description['kwargs'])
        else:
            raise Exception("Optimizer type " + optimizer_description['type'] + " not yet supported.")

        if self.get_run_index() == 0:  ##TODO ADD or (optimizer kwargs has changed from last run)
            self.log("Compiling the model.")
            self.model.compile(loss='binary_crossentropy', optimizer=optimizer, metrics=[])

        model_save_name = self.get_run_index_prefixed_path('trained.model')

        fraction_training_data_each_epoch = training_description['fraction_data_each_epoch']
        fraction_validation_data_each_epoch = validation_description['fraction_data_each_epoch']

        epochs = training_description['epochs']
        training_steps_per_epoch = int(
            fraction_training_data_each_epoch * training_note_sample_generator.get_total_batches_count())
        validation_steps_per_epoch = int(
            fraction_validation_data_each_epoch * validation_note_sample_generator.get_total_batches_count())

        self.log("Training steps per epoch: " + str(training_steps_per_epoch))
        self.log("Validation steps per epoch: " + str(validation_steps_per_epoch))

        checkpoint_callback = ModelCheckpoint(model_save_name,
                                              monitor='loss',
                                              verbose=0,
                                              save_best_only=False,
                                              save_weights_only=False,
                                              mode='auto',
                                              save_freq=1)

        save_state_callback = ExecuteEveryNBatchesCallback(
            run_frequency_in_batches=training_description['checkpoint_frequency_in_steps'],
            method_to_run=self.checkpoint_method_creator(training_note_sample_generator=training_note_sample_generator)
        )

        self.model.fit(
            x=training_note_sample_generator,
            epochs=epochs,
            verbose=1,
            steps_per_epoch=training_steps_per_epoch,
            validation_data=validation_note_sample_generator,
            validation_steps=validation_steps_per_epoch,
            callbacks=[checkpoint_callback, save_state_callback]
        )
