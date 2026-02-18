package agh.ics.oop.model;

import java.io.Serializable;

public class Configuration implements Serializable {
    private final int loseEnergyPerMove;
    private final int energyProvidedByPlant;
    private final int energyToReproduce;
    private final int energyLoseAfterReproduction;
    private final int plantsGrowingEveryDay;
    private final int startingEnergy;
    private final int numberOfStartingAnimals;
    private final int numberOfStartingPlants;
    private final int genotypeSize;
    private final boolean behaviorOption1Selected;
    private final boolean fertileSoilOptionSelected;


    public Configuration(int loseEnergyPerMove, int energyProvidedByPlant, int energyToReproduce, int energyLoseAfterReproduction, int plantsGrowingEveryDay, int startingEnergy, int numberOfStartingAnimals, int numberOfStartingPlants, int genotypeSize, boolean behaviorOption1Selected, boolean fertileSoilOptionSelected) {
        this.loseEnergyPerMove = loseEnergyPerMove;
        this.energyProvidedByPlant = energyProvidedByPlant;
        this.energyToReproduce = energyToReproduce;
        this.energyLoseAfterReproduction = energyLoseAfterReproduction;
        this.plantsGrowingEveryDay = plantsGrowingEveryDay;
        this.startingEnergy = startingEnergy;
        this.numberOfStartingAnimals = numberOfStartingAnimals;
        this.numberOfStartingPlants = numberOfStartingPlants;
        this.genotypeSize = genotypeSize;
        this.behaviorOption1Selected = behaviorOption1Selected;
        this.fertileSoilOptionSelected = fertileSoilOptionSelected;
    }

    public int getEnergyProvidedByPlant() {
        return energyProvidedByPlant;
    }

    public int getEnergyLoseAfterReproduction() {
        return energyLoseAfterReproduction;
    }

    public int getPlantsGrowingEveryDay() {
        return plantsGrowingEveryDay;
    }

    public int getStartingEnergy() {
        return startingEnergy;
    }

    public int getNumberOfStartingAnimals() {
        return numberOfStartingAnimals;
    }

    public int getNumberOfStartingPlants() {
        return numberOfStartingPlants;
    }

    public boolean isBehaviorOption1Selected() {
        return behaviorOption1Selected;
    }

    public boolean isFertileSoilOptionSelected() {
        return fertileSoilOptionSelected;
    }

    public int getGenotypeSize() {
        return genotypeSize;
    }

    public int getEnergyToReproduce() {
        return energyToReproduce;
    }

    public int getLoseEnergyPerMove() {
        return loseEnergyPerMove;
    }

    public String toString() {
        return "Config: \n " +
            "Energy provided by eating: " + getEnergyProvidedByPlant() + "\n" +
            "Energy lost after reproduction: " + getEnergyLoseAfterReproduction() + "\n" +
            "Plants growing every dat: " + getPlantsGrowingEveryDay() + "\n" +
            "Starting energy: " + getStartingEnergy() + "\n" +
            "Starting animals: " + getNumberOfStartingAnimals() + "\n" +
            "Starting plants: " + getNumberOfStartingPlants() + "\n" +
            "Behaviour option: " + isBehaviorOption1Selected() + "\n" +
            "Is fertile soil mode on: " + isFertileSoilOptionSelected() + "\n" +
            "Genotype size: " + getGenotypeSize() + "\n" +
            "Energy to reproduce: " + getEnergyToReproduce() + "\n" +
            "Energy lost after moving" + getLoseEnergyPerMove() + "\n";
    }
}