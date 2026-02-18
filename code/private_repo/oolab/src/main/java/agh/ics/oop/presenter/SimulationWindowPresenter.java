package agh.ics.oop.presenter;

import agh.ics.oop.*;
import agh.ics.oop.model.*;
import agh.ics.oop.util.SimulationStatistics;
import agh.ics.oop.util.AnimalStatistics;
import javafx.application.Platform;
import javafx.fxml.FXML;
import javafx.scene.control.Button;
import javafx.scene.layout.*;
import javafx.scene.control.Label;
import javafx.geometry.HPos;
import javafx.scene.Node;
import javafx.scene.paint.Color;
import javafx.scene.paint.Paint;
import javafx.scene.shape.Rectangle;
import javafx.stage.Stage;
import javafx.scene.shape.Circle;
import javafx.scene.shape.Line;

import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

public class SimulationWindowPresenter implements MapChangeListener {
    private Globe map;
    private Simulation simulation;
    private SimulationStatistics simulationStatistics;
    private static final double CELL_WIDTH = 30.0;
    private static final double CELL_HEIGHT = 30.0;
    private Animal selectedAnimal;
    private List<Vector2d> mostFrequentGrassPositions;
    private boolean collectData;
    private FileWriter csvWriter;

    @FXML
    private GridPane mapGrid;

    @FXML
    private Button pauseButton;
    @FXML
    private Button resumeButton;
    @FXML
    private Label animalCountLabel;
    @FXML
    private Label grassCountLabel;
    @FXML
    private Label freeFieldCountLabel;
    @FXML
    private Label mostPopularGenotypeLabel;
    @FXML
    private Label averageEnergyLevelOfAnimals;
    @FXML
    private Label averageLifeSpanOfAnimal;
    @FXML
    private Label averageNumberOfChildren;
    @FXML
    private Label animalInfoLabel;

    @FXML
    public void initialize() {
        pauseButton.setOnAction(event -> onPauseClicked());
        resumeButton.setOnAction(event -> onResumeClicked());
    }

    public void initializeSimulation(int mapWidth, int mapHeight, Configuration config, boolean collectData) {
        this.collectData = collectData;
        if (collectData) {
            try {
                String desktopPath = Paths.get(System.getProperty("user.home"), "Desktop", "animal_statistics.csv").toString();
                csvWriter = new FileWriter(desktopPath);
                csvWriter.append("Day,AnimalID,Genotype,ActiveGenotypePart,Energy,PlantsEaten,Children,Descendants,DaysLived,Status\n");
            } catch (IOException e) {
                e.printStackTrace();
            }
        }

        Globe map = new Globe(mapWidth, mapHeight, config);
        map.subscribe(this);
        setWorldMap(map);

        Simulation simulation = new Simulation(map);
        setSimulation(simulation);

        SimulationEngine.getInstance().addSimulation(simulation);
        SimulationEngine.getInstance().runAsyncInThreadPool();

        simulationStatistics = new SimulationStatistics(map);
        updateAnimalCount();
    }

    @FXML
    private void onPauseClicked() {
        simulation.pause();
        highlightAnimalsWithMostPopularGenotype();
        displayRedCross();
    }

    @FXML
    private void onResumeClicked() {
        simulation.resume();
        clearHighlights();
        removeRedCross();
    }

    @Override
    public void mapChanged(WorldMap worldMap) {
        Platform.runLater(() -> {
            drawMap(worldMap);
            updateAnimalCount();
            updateGrassCount();
            updateFreeFieldCount();
            updateMostPopularGenotype();
            updateAverageEnergyLevel();
            updateAverageLifeSpanOfAnimal();
            updateAverageNumberOfChildren();
            if (selectedAnimal != null) {
                displayAnimalData(selectedAnimal);
            }
            if (collectData) {
                collectStatistics();
            }
        });
    }

    private void collectStatistics() {
        int day = simulationStatistics.getCurrentDay();
        for (Animal animal : map.getAllAnimals().values()) {
            AnimalStatistics stats = animal.getStatistics();
            try {
                csvWriter.append(String.format("%d,%s,%s,%s,%d,%d,%d,%d,%d,%s\n",
                        day,
                        animal.getId(),
                        stats.getGenotype(),
                        stats.getActiveGenotypePart(),
                        stats.getEnergy(),
                        stats.getPlantsEaten(),
                        stats.getChildrenCount(),
                        stats.getDescendantsCount(),
                        stats.getDaysLived(),
                        stats.isAlive() ? "Alive" : "Dead"
                ));
            } catch (IOException e) {
                e.printStackTrace();
            }
        }
    }

    public void setStage(Stage stage) {
        stage.setOnCloseRequest(event -> {
            if (simulation != null) {
                SimulationEngine.getInstance().stopSimulation(simulation);
            }
            if (collectData) {
                try {
                    csvWriter.flush();
                    csvWriter.close();
                } catch (IOException e) {
                    e.printStackTrace();
                }
            }
        });
    }

    private void setWorldMap(Globe map) {
        this.map = map;
    }

    private void setSimulation(Simulation simulation) {
        this.simulation = simulation;
    }

    private void clearGrid() {
        mapGrid.getChildren().retainAll(mapGrid.getChildren().get(0)); // hack to retain visible grid lines
        mapGrid.getColumnConstraints().clear();
        mapGrid.getRowConstraints().clear();
    }

    public void drawMap(WorldMap map) {
        clearGrid();

        mapGrid.getColumnConstraints().add(new ColumnConstraints(CELL_WIDTH));
        for (int i = 0; i <= map.getWidth() - 1; i++) {
            mapGrid.getColumnConstraints().add(new ColumnConstraints(CELL_WIDTH));
        }
        mapGrid.getRowConstraints().add(new RowConstraints(CELL_HEIGHT));
        for (int j = 0; j <= map.getHeight() - 1; j++) {
            mapGrid.getRowConstraints().add(new RowConstraints(CELL_HEIGHT));
        }

        for (int i = 0; i <= map.getWidth() - 1; i++) {
            Label label = new Label(String.valueOf(i));
            GridPane.setHalignment(label, HPos.CENTER);
            mapGrid.add(label, i + 1, 0);
        }

        for (int j = 0; j <= map.getHeight() - 1; j++) {
            Label label = new Label(String.valueOf(map.getHeight() - j - 1));
            GridPane.setHalignment(label, HPos.CENTER);
            mapGrid.add(label, 0, j + 1);
        }

        for (int i = 0; i <= map.getWidth() - 1; i++) {
            for (int j = map.getHeight() - 1; j >= 0; j--) {
                Node node = createNodeForPosition(new Vector2d(i, j));
                mapGrid.add(node, i + 1, map.getHeight() - j);
            }
        }
    }

    private Node createNodeForPosition(Vector2d position) {
        StackPane stackPane = new StackPane();
        stackPane.setPrefSize(CELL_WIDTH, CELL_HEIGHT);

        Rectangle background = new Rectangle(CELL_WIDTH, CELL_HEIGHT);
        if (map.getConfig().isFertileSoilOptionSelected() && map.getDeadAnimalsZone().containsKey(position)) {
            background.setFill(Color.SADDLEBROWN); // Dark brown color for dead animal zone
        } else if (map.isInJungle(position)) {
            background.setFill(Color.BURLYWOOD); // Light brown color for jungle area
        } else {
            background.setFill(Color.YELLOWGREEN); // Color for non-jungle fields
        }
        stackPane.getChildren().add(background);

        if (map != null && map.isOccupied(position)) {
            Object object = map.objectAt(position);
            if (object instanceof Animal animal) {
                Circle circle = new Circle(12);
                circle.setFill(getColorForEnergy(animal.getEnergy()));
                circle.setStroke(Color.BLACK);
                circle.setOnMouseClicked(event -> {
                    highlightAnimal(animal, background);
                    displayAnimalData(animal);
                    drawMap(map);
                });
                stackPane.getChildren().add(circle);

                if (animal.equals(selectedAnimal)) {
                    background.setFill(Color.PURPLE);
                }
            } else if (object instanceof Grass) {
                Rectangle grassRect = new Rectangle(CELL_WIDTH, CELL_HEIGHT);
                grassRect.setFill(Color.LAWNGREEN);
                stackPane.getChildren().add(grassRect);
            } else {
                Label label = new Label(object.toString());
                GridPane.setHalignment(label, HPos.CENTER);
                stackPane.getChildren().add(label);
            }
        }

        return stackPane;
    }

    private void highlightAnimal(Animal animal, Rectangle background) {
        if (selectedAnimal != null && selectedAnimal.equals(animal)) {
            // Deselect the animal
            resetAnimalBackground(selectedAnimal);
            selectedAnimal = null;
            animalInfoLabel.setText(""); // Clear the animal info
            animalInfoLabel.setVisible(false); // Hide the label
            return;
        }

        if (selectedAnimal != null) {
            // Reset the color of the previously selected animal's field
            resetAnimalBackground(selectedAnimal);
        }

        // Highlight the selected animal's field
        background.setFill(Color.PURPLE);
        selectedAnimal = animal;
        displayAnimalData(animal);
        animalInfoLabel.setVisible(true); // Show the label
    }

    private void resetAnimalBackground(Animal animal) {
        Vector2d previousPosition = animal.getPosition();
        Node previousNode = getNodeByRowColumnIndex(previousPosition.getY(), previousPosition.getX(), mapGrid);
        if (previousNode instanceof StackPane previousStackPane) {
            Rectangle previousBackground = (Rectangle) previousStackPane.getChildren().get(0);
            if (map.isInJungle(previousPosition)) {
                previousBackground.setFill(Color.BURLYWOOD);
            } else {
                previousBackground.setFill(Color.YELLOWGREEN);
            }
        }
    }

    private Node getNodeByRowColumnIndex(final int row, final int column, GridPane gridPane) {
        for (Node node : gridPane.getChildren()) {
            Integer nodeRow = GridPane.getRowIndex(node);
            Integer nodeColumn = GridPane.getColumnIndex(node);
            if (nodeRow != null && nodeRow == row && nodeColumn != null && nodeColumn == column) {
                return node;
            }
        }
        return null;
    }

    private void displayAnimalData(Animal animal) {
        AnimalStatistics stats = animal.getStatistics();
        StringBuilder animalInfo = new StringBuilder();
        animalInfo.append("ID: ").append(animal.getId()).append("\n");
        animalInfo.append("Genotype: ").append(stats.getGenotype()).append("\n");
        animalInfo.append("Active Genotype Part: ").append(stats.getActiveGenotypePart()).append("\n");
        animalInfo.append("Energy: ").append(stats.getEnergy()).append("\n");
        animalInfo.append("Plants Eaten: ").append(stats.getPlantsEaten()).append("\n");
        animalInfo.append("Children: ").append(stats.getChildrenCount()).append("\n");
        animalInfo.append("Descendants: ").append(stats.getDescendantsCount()).append("\n");
        animalInfo.append("Days Lived: ").append(stats.getDaysLived()).append("\n");
        if (stats.isAlive()) {
            animalInfo.append("Status: Alive\n");
        } else {
            animalInfo.append("Death Day: ").append(stats.getDeathDay()).append("\n");
        }

        Platform.runLater(() -> animalInfoLabel.setText(animalInfo.toString()));
    }

    private Paint getColorForEnergy(int energy) {
        int maxEnergy = map.getConfig().getStartingEnergy();
        float energyPercentage = (float) energy / maxEnergy;

        if (energyPercentage <= 0.1) {
            return Color.DARKRED;
        } else if (energyPercentage <= 0.25) {
            return Color.RED;
        } else if (energyPercentage <= 0.5) {
            return Color.ORANGE;
        } else if (energyPercentage <= 0.75) {
            return Color.YELLOW;
        } else if (energyPercentage <= 1.0) {
            return Color.LIGHTGREEN;
        } else {
            return Color.DARKGREEN;
        }
    }

    private void highlightAnimalsWithMostPopularGenotype() {
        int mostPopularGenotype = simulationStatistics.getMostPopularGenotype();
        for (ArrayList<Animal> animals : map.getAnimalMap().values()) {
            for (Animal animal : animals) {
                if (animal.getGenotype().getGenes().contains(mostPopularGenotype)) {
                    highlightAnimal(animal);
                }
            }
        }
    }

    private void highlightAnimal(Animal animal) {
        Vector2d position = animal.getPosition();
        Node node = getNodeByRowColumnIndex(map.getHeight() - position.getY(), position.getX() + 1, mapGrid);
        if (node instanceof StackPane stackPane) {
            Rectangle background = (Rectangle) stackPane.getChildren().get(0);
            background.setStroke(Color.BLUE);
            background.setStrokeWidth(3);
        }
    }

    private void clearHighlights() {
        for (Node node : mapGrid.getChildren()) {
            if (node instanceof StackPane stackPane) {
                Rectangle background = (Rectangle) stackPane.getChildren().get(0);
                background.setStroke(null);
                background.setStrokeWidth(0);
            }
        }
    }

    private void updateAnimalCount() {
        int totalAnimals = simulationStatistics.getTotalAnimals();
        Platform.runLater(() -> animalCountLabel.setText("Animals: " + totalAnimals));
    }

    public void updateGrassCount(){
        int totalGrass = simulationStatistics.getTotalGrass();
        Platform.runLater(() -> grassCountLabel.setText("Grass: " + totalGrass));
    }

    public void updateFreeFieldCount(){
        int freeFields = simulationStatistics.getFreeFields();
        Platform.runLater(() -> freeFieldCountLabel.setText("Free fields: " + freeFields));
    }

    public void updateMostPopularGenotype(){
        int mostPopularGenotype = simulationStatistics.getMostPopularGenotype();
        Platform.runLater(() -> mostPopularGenotypeLabel.setText("Most popular genotype: " + mostPopularGenotype));
    }

    public void updateAverageEnergyLevel(){
        int averageEnergyLevel = simulationStatistics.averageEnergyLevelOfAnimals();
        Platform.runLater(() -> averageEnergyLevelOfAnimals.setText("Average energy level: " + averageEnergyLevel));
    }

    public void updateAverageLifeSpanOfAnimal(){
        int averageLifeSpan = simulationStatistics.averageLifeSpanOfAnimal();
        Platform.runLater(() -> averageLifeSpanOfAnimal.setText("Average life span: " + averageLifeSpan));
    }

    public void updateAverageNumberOfChildren(){
        float averageNumberOfChildren = simulationStatistics.averageNumberOfChildren();
        Platform.runLater(() -> this.averageNumberOfChildren.setText("Average number of children: " + averageNumberOfChildren));
    }

    private void displayRedCross() {
        mostFrequentGrassPositions = simulationStatistics.getMostFrequentGrassPositions();
        for (Vector2d position : mostFrequentGrassPositions) {
            drawRedCross(position);
        }
    }

    private void removeRedCross() {
        if (mostFrequentGrassPositions != null) {
            for (Vector2d position : mostFrequentGrassPositions) {
                clearRedCross(position);
            }
        }
    }

    private void drawRedCross(Vector2d position) {
        Line line1 = new Line(0, 0, CELL_WIDTH, CELL_HEIGHT);
        Line line2 = new Line(CELL_WIDTH, 0, 0, CELL_HEIGHT);
        line1.setStroke(Color.RED);
        line2.setStroke(Color.RED);

        Node node = getNodeByRowColumnIndex(map.getHeight() - position.getY(), position.getX() + 1, mapGrid);
        if (node instanceof StackPane stackPane) {
            stackPane.getChildren().addAll(line1, line2);
        }
    }

    private void clearRedCross(Vector2d position) {
        Node node = getNodeByRowColumnIndex(map.getHeight() - position.getY(), position.getX() + 1, mapGrid);
        if (node instanceof StackPane stackPane) {
            List<Node> linesToRemove = new ArrayList<>();
            for (Node child : stackPane.getChildren()) {
                if (child instanceof Line) {
                    linesToRemove.add(child);
                }
            }
            stackPane.getChildren().removeAll(linesToRemove);
        }
    }
}