package agh.ics.oop.util;

import agh.ics.oop.model.Animal;
import agh.ics.oop.model.Globe;
import agh.ics.oop.model.Vector2d;

import java.util.List;
import java.util.Map;
import java.util.HashMap;
import java.util.ArrayList;

public class SimulationStatistics {
    private final Globe globe;
    private final int totalFields;

    public SimulationStatistics(Globe globe){
        this.globe = globe;
        this.totalFields = globe.getHeight()* globe.getWidth();
    }

    public int getCurrentDay() {
        return globe.getCurrentDay();
    }

    public int getTotalAnimals() {
        return globe.getAnimalCount();

    }

    public int getTotalGrass() {
        return globe.getGrassCount();
    }

    public List<Animal> getCurrentLivingAnimals() {
        return globe.getLivingAnimals();
    }
    public List<Animal> getCurrentDeadAnimals() {
        return globe.getDeadAnimals();
    }


    public int getFreeFields() {
        // można pomyśleć czy jak zwierzak jest na jakimś polu to czy jest ono też zajęte ale nwm jak to interpreotwać.
        return totalFields - getTotalGrass();
    }

    public int getMostPopularGenotype() {
        Map<Integer, Integer> genotypeCount = globe.getGenotypeCount();
        return genotypeCount.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .map(Map.Entry::getKey)
                .orElse(-1);
    }

    public Map<Vector2d, Integer> countGrassOccurrences() {
        Map<Vector2d, Integer> grassOccurrences = new HashMap<>();
        for (Vector2d position : globe.getAllGrassPositions()) {
            grassOccurrences.merge(position, 1, Integer::sum);
        }
        return grassOccurrences;
    }

    public List<Vector2d> getMostFrequentGrassPositions() {
        Map<Vector2d, Integer> grassOccurrences = countGrassOccurrences();
        int maxCount = grassOccurrences.values().stream().max(Integer::compare).orElse(0);
        List<Vector2d> mostFrequentPositions = new ArrayList<>();
        for (Map.Entry<Vector2d, Integer> entry : grassOccurrences.entrySet()) {
            if (entry.getValue() == maxCount) {
                mostFrequentPositions.add(entry.getKey());
            }
        }
        return mostFrequentPositions;
    }



    public int averageEnergyLevelOfAnimals(){
        List<Animal> livingAnimals = getCurrentLivingAnimals();
        if (livingAnimals.isEmpty()) {
            return 0;
        }
        int totalEnergy = livingAnimals.stream().mapToInt(Animal::getEnergy).sum();
        return totalEnergy / livingAnimals.size();
    }
    public int averageLifeSpanOfAnimal(){
        List<Animal> getDeadAnimals = getCurrentDeadAnimals();
        if (getDeadAnimals.isEmpty()) {
            return 0;
        }
        int totalEnergy = getDeadAnimals.stream().mapToInt(Animal::getAge).sum();
        return totalEnergy / getDeadAnimals.size();

    }

    // SimulationStatistics.java
    public float averageNumberOfChildren() {
        List<Animal> livingAnimals = getCurrentLivingAnimals();
        if (livingAnimals.isEmpty()) {
            return 0;
        }
        int totalChildren = livingAnimals.stream().mapToInt(animal -> animal.getChildrenIds().size()).sum();
        return (float) totalChildren / livingAnimals.size();
    }
}