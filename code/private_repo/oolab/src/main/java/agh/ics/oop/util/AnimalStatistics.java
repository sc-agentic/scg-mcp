package agh.ics.oop.util;

import agh.ics.oop.model.Animal;
import agh.ics.oop.model.Globe;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

public class AnimalStatistics {
    private final Globe globe;
    private final Animal animal;
    private int plantsEaten;
    private int childrenCount;
    private int daysLived;
    private int deathDay;

    public AnimalStatistics(Globe globe,Animal animal) {
        this.globe =  globe;
        this.animal = animal;
        this.plantsEaten = 0;
        this.childrenCount = 0;
        this.daysLived = 0;
        this.deathDay = -1; // -1 indicates the animal is still alive
    }

    public ArrayList<Integer> getGenotype() {
        return globe.getAnimalGenes(animal);
    }

    public String getActiveGenotypePart() {
        int index = globe.getAnimalLastUsedGeneIndex(animal);
        ArrayList<Integer> genes = getGenotype();
        return "index: " +index + " gene: " + genes.get(index);
    }

    public int getEnergy() {
        return globe.getAnimalEnergy(animal);
    }

    public int getDescendantsCount() {
        Map<UUID, Animal> allAnimals = globe.getAllAnimals();
        Set<UUID> descendants = new HashSet<>();
        collectDescendants(animal, allAnimals, descendants);
        return descendants.size();
    }

    private void collectDescendants(Animal animal, Map<UUID, Animal> allAnimals, Set<UUID> descendants) {
        for (UUID childId : animal.getChildrenIds()) {
            if (descendants.add(childId)) {
                Animal child = allAnimals.get(childId);
                if (child != null) {
                    collectDescendants(child, allAnimals, descendants);
                }
            }
        }
    }


    public int getPlantsEaten() {
        return plantsEaten;
    }

    public void incrementPlantsEaten() {
        this.plantsEaten++;
    }

    public int getChildrenCount() {
        return childrenCount;
    }

    public void incrementChildrenCount() {
        this.childrenCount++;
    }

    public int getDaysLived() {
        return daysLived;
    }

    public void incrementDaysLived() {
        this.daysLived++;
    }

    public int getDeathDay() {
        return deathDay;
    }

    public boolean isAlive() {
        return deathDay == -1;
    }
}