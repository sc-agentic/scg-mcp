package agh.ics.oop.model;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class Globe implements WorldMap {
    private final UUID id = UUID.randomUUID();
    private final int width;
    private final int height;
    private final Map<Vector2d, Integer> deadAnimalsZone = new HashMap<>();
    private final Map<Vector2d, Grass> grassMap = new HashMap<>();
    private final Set<Vector2d> allGrassPositions = new HashSet<>(); // New variable
    private final Map<Vector2d, ArrayList<Animal>> animalMap = new ConcurrentHashMap<>();
    private final Map<Vector2d, ArrayList<Animal>> deadAnimalMap = new HashMap<>();
    private final int jungleHeight;
    private int currentDay = 0;

    private final Configuration config;

    private final ArrayList<MapChangeListener> listeners = new ArrayList<>();

    public Globe(int width, int height, Configuration config) {
        this.width = width;
        this.height = height;
        this.config = config;

        jungleHeight = (int) Math.round(height * 0.2);
    }

    @Override
    public UUID getId() {
        return id;
    }

    public int getWidth() {
        return width;
    }

    public int getHeight() {
        return height;
    }

    public Map<Vector2d, ArrayList<Animal>> getAnimalMap() {
        return animalMap;
    }

    public Configuration getConfig() {
        return config;
    }

    public int getAnimalCount() {
        int count = 0;
        for (ArrayList<Animal> animals : animalMap.values()) {
            count += animals.size();
        }
        return count;
    }

    public int getGrassCount() {
        return grassMap.size();
    }

    public Set<Vector2d> getAllGrassPositions() {
        return allGrassPositions;
    }
    public int getCurrentDay() {
        return currentDay;
    }

    public Map<Integer, Integer> getGenotypeCount() {
        Map<Integer, Integer> geneCount = new ConcurrentHashMap<>();
        for (int i = 0; i <= 7; i++) {
            geneCount.put(i, 0);
        }

        for (ArrayList<Animal> animals : animalMap.values()) {
            for (Animal animal : animals) {
                for (int gene : animal.getGenotype().getGenes()) {
                    geneCount.merge(gene, 1, Integer::sum);
                }
            }
        }
        return geneCount;
    }

    public List<Animal> getLivingAnimals() {
        List<Animal> livingAnimals = new ArrayList<>();
        for (ArrayList<Animal> animals : animalMap.values()) {
            livingAnimals.addAll(animals);
        }
        return livingAnimals;
    }

    public int getAnimalEnergy(Animal animal) {
        if (animalMap.containsKey(animal.getPosition())) {
            for (Animal a : animalMap.get(animal.getPosition())) {
                if (a.equals(animal)) {
                    return a.getEnergy();
                }
            }
        }
        return 0;
    }

    public Genotype getAnimalGenotype(Animal animal) {
        return animal.getGenotype();
    }

    public ArrayList<Integer> getAnimalGenes(Animal animal) {
        return getAnimalGenotype(animal).getGenes();
    }

    public int getAnimalLastUsedGeneIndex(Animal animal) {
        return getAnimalGenotype(animal).getLastUsedGeneIndex();
    }

    public List<Animal> getDeadAnimals() {
        List<Animal> DeathAnimals = new ArrayList<>();
        for (ArrayList<Animal> animals : deadAnimalMap.values()) {
            DeathAnimals.addAll(animals);
        }
        return DeathAnimals;
    }

    public Map<UUID, Animal> getAllAnimals() {
        Map<UUID, Animal> allAnimals = new HashMap<>();
        for (ArrayList<Animal> animals : animalMap.values()) {
            for (Animal animal : animals) {
                allAnimals.put(animal.getId(), animal);
            }
        }
        for (ArrayList<Animal> animals : deadAnimalMap.values()) {
            for (Animal animal : animals) {
                allAnimals.put(animal.getId(), animal);
            }
        }
        return allAnimals;
    }

    public Map<Vector2d, Integer> getDeadAnimalsZone() {
        return deadAnimalsZone;
    }

    @Override
    public Vector2d validateMove(Vector2d initialPosition, Vector2d targetPosition) {
        if (targetPosition.getY() < 0 || targetPosition.getY() >= height) {
            return initialPosition;
        }

        if (targetPosition.getX() < 0) {
            return new Vector2d(width - 1, targetPosition.getY());
        } else if (targetPosition.getX() >= width) {
            return new Vector2d(0, targetPosition.getY());
        }
        return targetPosition;
    }

    @Override
    public MapDirection validateDirection(Vector2d targetPosition, MapDirection direction) {
        if (targetPosition.getY() < 0 || targetPosition.getY() >= height) {
            return direction.rotate(4);
        }
        return direction;
    }

    @Override
    public void animalMoved(Vector2d oldPosition, Vector2d newPosition, Animal animal) {
        if (animalMap.containsKey(oldPosition)) {
            animalMap.get(oldPosition).remove(animal);
            if (animalMap.get(oldPosition).isEmpty()) {
                animalMap.remove(oldPosition);
            }
        }
        if (!animalMap.containsKey(newPosition)) {
            animalMap.put(newPosition, new ArrayList<>());
        }
        animalMap.get(newPosition).add(animal);
        mapChanged();
    }

    private void spawnAnimals(int count) {
        for (int i = 0; i < count; i++) {
            Animal animal = new Animal(this);
            if (!animalMap.containsKey(animal.getPosition())) {
                animalMap.put(animal.getPosition(), new ArrayList<>());
            }
            animalMap.get(animal.getPosition()).add(animal);
            animal.subscribe(this);
        }
        mapChanged();
    }

    private ArrayList<Vector2d> getAvailableFertilePositions(int jungleStart, int jungleEnd) {
        ArrayList<Vector2d> availableJunglePositions = new ArrayList<>();
        for (int i = jungleStart; i < jungleEnd; i++) {
            for (int j = 0; j < width; j++) {
                Vector2d possibleGrassPosition = new Vector2d(j, i);
                if (!grassMap.containsKey(possibleGrassPosition)) {
                    availableJunglePositions.add(possibleGrassPosition);
                }
            }
        }

        for (Vector2d position : deadAnimalsZone.keySet()) {
            if (!availableJunglePositions.contains(position)) {
                availableJunglePositions.add(position);
            }
        }
        return availableJunglePositions;
    }

    private ArrayList<Vector2d> getAvailableNormalGrassPositions(int jungleStart) {
        ArrayList<Vector2d> availableSteppePositions = new ArrayList<>();
        for (int i = 0; i < jungleStart; i++) {
            for (int j = 0; j < width; j++) {
                Vector2d possibleGrassPosition = new Vector2d(j, i);
                if (!grassMap.containsKey(possibleGrassPosition)) {
                    availableSteppePositions.add(possibleGrassPosition);
                }
            }
        }

        for (int i = jungleStart + jungleHeight; i < height; i++) {
            for (int j = 0; j < width; j++) {
                Vector2d possibleGrassPosition = new Vector2d(j, i);
                if (!grassMap.containsKey(possibleGrassPosition)) {
                    availableSteppePositions.add(possibleGrassPosition);
                }
            }
        }
        return availableSteppePositions;
    }

    public boolean isInJungle(Vector2d position) {
        int jungleStart = (height - jungleHeight) / 2;
        int jungleEnd = jungleStart + jungleHeight;
        return position.getY() >= jungleStart && position.getY() < jungleEnd;
    }

    private void spawnGrass(int count) {
        int jungleStart = (height - jungleHeight) / 2;
        int jungleEnd = jungleStart + jungleHeight;

        ArrayList<Vector2d> availableJunglePositions = getAvailableFertilePositions(jungleStart, jungleEnd);
        ArrayList<Vector2d> availableSteppePositions = getAvailableNormalGrassPositions(jungleStart);

        count = Math.min(count, availableJunglePositions.size() + availableSteppePositions.size());

        int jungleGrassCount = 0;
        for (int i = 0; i < count; i++) {
            if (Math.random() < 0.8) {
                jungleGrassCount += 1;
            }
        }
        jungleGrassCount = Math.min(jungleGrassCount, availableJunglePositions.size());
        RandomPositionGenerator jungleGenerator = new RandomPositionGenerator(availableJunglePositions, jungleGrassCount);
        for (Vector2d position : jungleGenerator) {
            grassMap.put(position, new Grass(position));
            allGrassPositions.add(position); // Update all grass positions
        }

        int steppeGrassCount = count - jungleGrassCount;
        RandomPositionGenerator steppeGenerator = new RandomPositionGenerator(availableSteppePositions, steppeGrassCount);
        for (Vector2d position : steppeGenerator) {
            grassMap.put(position, new Grass(position));
            allGrassPositions.add(position); // Update all grass positions
        }
        mapChanged();
    }

    public WorldElement objectAt(Vector2d position) {
        if (animalMap.containsKey(position)) {
            return animalMap.get(position).get(0);
        }
        if (grassMap.containsKey(position)) {
            return grassMap.get(position);
        }
        return null;
    }

    public boolean isOccupied(Vector2d position) {
        return animalMap.containsKey(position) || grassMap.containsKey(position);
    }

    public void subscribe(MapChangeListener listener) {
        listeners.add(listener);
    }

    private void mapChanged() {
        for (MapChangeListener listener : listeners) {
            listener.mapChanged(this);
        }
    }

    private void moveAnimalToDeadMap(Animal animal) {
        animalMap.get(animal.getPosition()).remove(animal);
        if (animalMap.get(animal.getPosition()).isEmpty()) {
            animalMap.remove(animal.getPosition());
        }
        if (!deadAnimalMap.containsKey(animal.getPosition())) {
            deadAnimalMap.put(animal.getPosition(), new ArrayList<>());
        }
        deadAnimalMap.get(animal.getPosition()).add(animal);
    }

    private void setDeadAnimalsZone(Vector2d position) {
        for (Vector2d surroundingPosition : position.getSurroundingPositions()) {
            if (surroundingPosition.getX() >= 0 && surroundingPosition.getX() < width && surroundingPosition.getY() >= 0 && surroundingPosition.getY() < height) {
                deadAnimalsZone.put(surroundingPosition, 10);
            }
        }
    }

    private void handleDeadZone() {
        if (!config.isFertileSoilOptionSelected()) {
            return;
        }

        ArrayList<Vector2d> positionsToRemove = new ArrayList<>();
        for (Vector2d position : deadAnimalsZone.keySet()) {
            deadAnimalsZone.put(position, deadAnimalsZone.get(position) - 1);
            if (deadAnimalsZone.get(position) == 0) {
                positionsToRemove.add(position);
            }
        }

        for (Vector2d position : positionsToRemove) {
            deadAnimalsZone.remove(position);
        }
        mapChanged();
    }

    private void removeDeadAnimals() {
        List<Animal> animals = new ArrayList<>();
        animalMap.values().forEach(animals::addAll);
        if (config.isFertileSoilOptionSelected()) {
            handleDeadZone();
        }
        for (Animal animal : animals) {
            if (animal.getEnergy() <= 0) {
                moveAnimalToDeadMap(animal);
                setDeadAnimalsZone(animal.getPosition());
            }
        }
    }

    private void moveAnimals() {
        List<Animal> animals = new ArrayList<>();
        animalMap.values().forEach(animals::addAll);

        for (Animal animal : animals) {
            animal.move();
        }
    }

    private void feedAnimals() {
        ArrayList<Vector2d> deletedGrass = new ArrayList<>();
        for (Vector2d position : grassMap.keySet()) {
            if (animalMap.containsKey(position)) {
                ArrayList<Animal> animals = animalMap.get(position);
                Animal.resolveConflict(animals, 1);
                animals.get(0).eat();
                deletedGrass.add(position);
            }
        }

        for (Vector2d position : deletedGrass) {
            grassMap.remove(position);
        }
    }

    private void reproduceAnimals() {
        for (ArrayList<Animal> animals : animalMap.values()) {
            Animal.resolveConflict(animals, 2);
            if (animals.size() >= 2 && animals.get(0).canReproduce() && animals.get(1).canReproduce()) {
                Animal child = Animal.reproduce(animals.get(0), animals.get(1));
                animalMap.get(child.getPosition()).add(child);
                child.subscribe(this);
            }
        }
    }

    public void initialSpawn() {
        spawnAnimals(config.getNumberOfStartingAnimals());
        spawnGrass(config.getNumberOfStartingPlants());
    }

    public void nextDay() {
        currentDay++;
        removeDeadAnimals();
        moveAnimals();
        feedAnimals();
        reproduceAnimals();
        spawnGrass(config.getPlantsGrowingEveryDay());
    }
}