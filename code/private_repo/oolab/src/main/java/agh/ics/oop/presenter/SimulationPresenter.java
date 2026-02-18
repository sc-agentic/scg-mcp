package agh.ics.oop.presenter;

import agh.ics.oop.model.Configuration;
import javafx.fxml.FXML;
import javafx.fxml.FXMLLoader;
import javafx.scene.Parent;
import javafx.scene.Scene;
import javafx.scene.control.*;
import javafx.stage.Stage;

import java.io.*;
import java.util.*;

public class SimulationPresenter {
    @FXML
    private ComboBox<String> presetComboBox;

    @FXML
    private TextField simulationMapHeight;
    @FXML
    private TextField simulationMapWidth;
    @FXML
    private TextField simulationNumberOfPlants;
    @FXML
    private TextField simulationAmountOfEnergyProvidedByThePlant;
    @FXML
    private TextField simulationNumberOfPlantsGrowingEveryDay;
    @FXML
    private TextField simulationNumberOfStartingAnimals;
    @FXML
    private TextField simulationNumberOfStartingEnergy;
    @FXML
    private TextField simulationNumberOfLoseEnergyPerMove;
    @FXML
    private TextField simulationNumberOfEnergyToReproduction;
    @FXML
    private TextField simulationNumberOfEnergyLoseAfterReproduction;
    @FXML
    private TextField simulationMinimalNumberOfMutations;
    @FXML
    private TextField simulationMaximalNumberOfMutations;
    @FXML
    private TextField simulationNumberOfPlacesForMutations;
    @FXML
    private RadioButton plantRadioOption1;
    @FXML
    private RadioButton plantRadioOption2;
    @FXML
    private RadioButton animalBehaviorOption1;
    @FXML
    private RadioButton animalBehaviorOption2;
    @FXML
    private CheckBox collectDataCheckbox;

    @FXML
    private Label moveDescriptionLabel;

    private ToggleGroup plantToggleGroup;
    private ToggleGroup animalBehaviorToggleGroup;

    private Map<String, Map<String, String>> presets = new HashMap<>();
    private static final String PRESETS_FILE = "../presets.ser";

    @FXML
    public void initialize() {
        loadPresets();
        presetComboBox.setOnAction(event -> onPresetSelected());

        // Initialize ToggleGroup for plant options
        plantToggleGroup = new ToggleGroup();
        plantRadioOption1.setToggleGroup(plantToggleGroup);
        plantRadioOption2.setToggleGroup(plantToggleGroup);

        // Initialize ToggleGroup for animal behavior options
        animalBehaviorToggleGroup = new ToggleGroup();
        animalBehaviorOption1.setToggleGroup(animalBehaviorToggleGroup);
        animalBehaviorOption2.setToggleGroup(animalBehaviorToggleGroup);

        // Optionally set default options
        plantRadioOption1.setSelected(true);
        animalBehaviorOption1.setSelected(true);

        // Add integer input filters to all TextFields
        addIntegerInputFilter(simulationMapHeight);
        addIntegerInputFilter(simulationMapWidth);
        addIntegerInputFilter(simulationNumberOfPlants);
        addIntegerInputFilter(simulationAmountOfEnergyProvidedByThePlant);
        addIntegerInputFilter(simulationNumberOfPlantsGrowingEveryDay);
        addIntegerInputFilter(simulationNumberOfStartingAnimals);
        addIntegerInputFilter(simulationNumberOfStartingEnergy);
        addIntegerInputFilter(simulationNumberOfLoseEnergyPerMove);
        addIntegerInputFilter(simulationNumberOfEnergyToReproduction);
        addIntegerInputFilter(simulationNumberOfEnergyLoseAfterReproduction);
        addIntegerInputFilter(simulationMinimalNumberOfMutations);
        addIntegerInputFilter(simulationMaximalNumberOfMutations);
        addIntegerInputFilter(simulationNumberOfPlacesForMutations);
    }

    private void addIntegerInputFilter(TextField textField) {
        textField.textProperty().addListener((observable, oldValue, newValue) -> {
            if (!newValue.matches("\\d*")) {
                textField.setText(newValue.replaceAll("\\D", ""));
            }
        });
    }

    @FXML
    private void onSavePresetClicked() {
        TextInputDialog dialog = new TextInputDialog();
        dialog.setTitle("Save Preset");
        dialog.setHeaderText("Enter preset name:");
        Optional<String> result = dialog.showAndWait();
        result.ifPresent(this::savePreset);
    }

    @FXML
    private void onDeletePresetClicked() {
        String selectedPreset = presetComboBox.getValue();
        if (selectedPreset != null) {
            presets.remove(selectedPreset);
            presetComboBox.getItems().remove(selectedPreset);
            savePresetsToFile();
        }
    }

    @FXML
    private void onSimulationStartClicked() {
        // Get selected plant option
        RadioButton selectedPlantOption = (RadioButton) plantToggleGroup.getSelectedToggle();
        if (selectedPlantOption == null) {
            moveDescriptionLabel.setText("No plant option selected!");
            return;
        }

        // Get selected animal behavior option
        RadioButton selectedAnimalBehaviorOption = (RadioButton) animalBehaviorToggleGroup.getSelectedToggle();
        if (selectedAnimalBehaviorOption == null) {
            moveDescriptionLabel.setText("No animal behavior option selected!");
            return;
        }

        // Use selected options
        boolean fertileSoilOptionSelected = plantRadioOption2.isSelected();
        boolean behaviorOption1Selected = animalBehaviorOption1.isSelected();

        // Get map dimensions and number of plants and animals
        int mapHeight;
        int mapWidth;
        int numberOfPlants;
        int numberOfAnimals;
        int loseEnergyPerMove;
        int energyProvidedByPlant;
        int energyToReproduce;
        int energyLoseAfterReproduction;
        int plantsGrowingEveryDay;
        int startingEnergy;
        int genotypeSize;

        try {
            mapHeight = Integer.parseInt(simulationMapHeight.getText());
            mapWidth = Integer.parseInt(simulationMapWidth.getText());
            numberOfPlants = Integer.parseInt(simulationNumberOfPlants.getText());
            numberOfAnimals = Integer.parseInt(simulationNumberOfStartingAnimals.getText());
            loseEnergyPerMove = Integer.parseInt(simulationNumberOfLoseEnergyPerMove.getText());
            energyProvidedByPlant = Integer.parseInt(simulationAmountOfEnergyProvidedByThePlant.getText());
            energyToReproduce = Integer.parseInt(simulationNumberOfEnergyToReproduction.getText());
            energyLoseAfterReproduction = Integer.parseInt(simulationNumberOfEnergyLoseAfterReproduction.getText());
            plantsGrowingEveryDay = Integer.parseInt(simulationNumberOfPlantsGrowingEveryDay.getText());
            startingEnergy = Integer.parseInt(simulationNumberOfStartingEnergy.getText());
            genotypeSize = Integer.parseInt(simulationNumberOfPlacesForMutations.getText());
        } catch (NumberFormatException e) {
            moveDescriptionLabel.setText("Invalid input: " + e.getMessage());
            return;
        }

        Configuration config = new Configuration(
                loseEnergyPerMove,
                energyProvidedByPlant,
                energyToReproduce,
                energyLoseAfterReproduction,
                plantsGrowingEveryDay,
                startingEnergy,
                numberOfAnimals,
                numberOfPlants,
                genotypeSize,
                behaviorOption1Selected,
                fertileSoilOptionSelected
        );

        boolean collectData = collectDataCheckbox.isSelected();

        try {
            FXMLLoader loader = new FXMLLoader(getClass().getResource("/simulationWindow.fxml"));
            Parent root = loader.load();

            Stage stage = new Stage();
            SimulationWindowPresenter simulationWindowPresenter = loader.getController();
            simulationWindowPresenter.initializeSimulation(mapWidth, mapHeight, config, collectData);
            simulationWindowPresenter.setStage(stage);

            stage.setTitle("Simulation Window");
            stage.setHeight(600);
            stage.setWidth(800);
            stage.setScene(new Scene(root));
            stage.show();
        } catch (IOException e) {
            e.printStackTrace();
        }

        moveDescriptionLabel.setText("Simulation started with plant option: " + selectedPlantOption.getText() + ", and animal behavior option: " + selectedAnimalBehaviorOption.getText());
    }

    private void onPresetSelected() {
        String selectedPreset = presetComboBox.getValue();
        if (selectedPreset != null) {
            Map<String, String> preset = presets.get(selectedPreset);
            if (preset != null) {
                loadPresetValues(preset);
            }
        }
    }

    private void savePreset(String presetName) {
        Map<String, String> preset = new HashMap<>();
        preset.put("simulationMapHeight", simulationMapHeight.getText());
        preset.put("simulationMapWidth", simulationMapWidth.getText());
        preset.put("simulationNumberOfPlants", simulationNumberOfPlants.getText());
        preset.put("simulationAmountOfEnergyProvidedByThePlant", simulationAmountOfEnergyProvidedByThePlant.getText());
        preset.put("simulationNumberOfPlantsGrowingEveryDay", simulationNumberOfPlantsGrowingEveryDay.getText());
        preset.put("simulationNumberOfStartingAnimals", simulationNumberOfStartingAnimals.getText());
        preset.put("simulationNumberOfStartingEnergy", simulationNumberOfStartingEnergy.getText());
        preset.put("simulationNumberOfLoseEnergyPerMove", simulationNumberOfLoseEnergyPerMove.getText());
        preset.put("simulationNumberOfEnergyToReproduction", simulationNumberOfEnergyToReproduction.getText());
        preset.put("simulationNumberOfEnergyLoseAfterReproduction", simulationNumberOfEnergyLoseAfterReproduction.getText());
        preset.put("simulationMinimalNumberOfMutations", simulationMinimalNumberOfMutations.getText());
        preset.put("simulationMaximalNumberOfMutations", simulationMaximalNumberOfMutations.getText());
        preset.put("simulationNumberOfPlacesForMutations", simulationNumberOfPlacesForMutations.getText());
        preset.put("plantRadioOption1", String.valueOf(plantRadioOption1.isSelected()));
        preset.put("plantRadioOption2", String.valueOf(plantRadioOption2.isSelected()));
        preset.put("animalBehaviorOption1", String.valueOf(animalBehaviorOption1.isSelected()));
        preset.put("animalBehaviorOption2", String.valueOf(animalBehaviorOption2.isSelected()));

        presets.put(presetName, preset);
        presetComboBox.getItems().add(presetName);
        savePresetsToFile();
    }

    private void loadPresetValues(Map<String, String> preset) {
        simulationMapHeight.setText(preset.get("simulationMapHeight"));
        simulationMapWidth.setText(preset.get("simulationMapWidth"));
        simulationNumberOfPlants.setText(preset.get("simulationNumberOfPlants"));
        simulationAmountOfEnergyProvidedByThePlant.setText(preset.get("simulationAmountOfEnergyProvidedByThePlant"));
        simulationNumberOfPlantsGrowingEveryDay.setText(preset.get("simulationNumberOfPlantsGrowingEveryDay"));
        simulationNumberOfStartingAnimals.setText(preset.get("simulationNumberOfStartingAnimals"));
        simulationNumberOfStartingEnergy.setText(preset.get("simulationNumberOfStartingEnergy"));
        simulationNumberOfLoseEnergyPerMove.setText(preset.get("simulationNumberOfLoseEnergyPerMove"));
        simulationNumberOfEnergyToReproduction.setText(preset.get("simulationNumberOfEnergyToReproduction"));
        simulationNumberOfEnergyLoseAfterReproduction.setText(preset.get("simulationNumberOfEnergyLoseAfterReproduction"));
        simulationMinimalNumberOfMutations.setText(preset.get("simulationMinimalNumberOfMutations"));
        simulationMaximalNumberOfMutations.setText(preset.get("simulationMaximalNumberOfMutations"));
        simulationNumberOfPlacesForMutations.setText(preset.get("simulationNumberOfPlacesForMutations"));
        plantRadioOption1.setSelected(Boolean.parseBoolean(preset.get("plantRadioOption1")));
        plantRadioOption2.setSelected(Boolean.parseBoolean(preset.get("plantRadioOption2")));
        animalBehaviorOption1.setSelected(Boolean.parseBoolean(preset.get("animalBehaviorOption1")));
        animalBehaviorOption2.setSelected(Boolean.parseBoolean(preset.get("animalBehaviorOption2")));
    }

    private void loadPresets() {
        try (ObjectInputStream ois = new ObjectInputStream(new FileInputStream(PRESETS_FILE))) {
            presets = (Map<String, Map<String, String>>) ois.readObject();
            presetComboBox.getItems().addAll(presets.keySet());
        } catch (IOException | ClassNotFoundException e) {
            e.printStackTrace();
        }
    }

    private void savePresetsToFile() {
        try (ObjectOutputStream oos = new ObjectOutputStream(new FileOutputStream(PRESETS_FILE))) {
            oos.writeObject(presets);
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}