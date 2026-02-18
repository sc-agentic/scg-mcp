package agh.ics.oop.model;

import agh.ics.oop.util.AnimalStatistics;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;

public class Animal implements WorldElement {
    private final UUID id = UUID.randomUUID();
    private Vector2d position;
    private MapDirection direction;
    private int energy;
    private final Genotype genotype;
    private int age = 0;
    private final List<AnimalMovedListener> listeners = new ArrayList<>();
    private final Globe map;
    private final List<UUID> childrenIds = new ArrayList<>();
    private final AnimalStatistics statistics;

    public Animal(Vector2d position, Genotype genotype, Globe map, int energy) {
        this.position = position;
        this.genotype = genotype;
        this.map = map;
        this.energy = energy;
        this.direction = MapDirection.values()[(int) (Math.random() * 7)];
        this.statistics = new AnimalStatistics(map, this);
    }

    public Animal(Globe map) {
        this(
                new Vector2d((int) (Math.random() * 10), (int) (Math.random() * 10)),
                new Genotype(map.getConfig().getGenotypeSize()),
                map,
                map.getConfig().getStartingEnergy()
        );
    }

    public UUID getId() {
        return id;
    }

    public Vector2d getPosition() {
        return position;
    }


    public int getEnergy() {
        return energy;
    }

    public int getAge() {
        return age;
    }

    public Genotype getGenotype() {
        return genotype;
    }

    public List<UUID> getChildrenIds() {
        return childrenIds;
    }

    public AnimalStatistics getStatistics() {
        return statistics;
    }



    public void addChild(Animal child) {
        childrenIds.add(child.getId());
        statistics.incrementChildrenCount();
    }

    public void incrementDaysLived() {
        statistics.incrementDaysLived();
    }



    @Override
    public String toString() {
        return direction.toString();
    }



    private boolean shouldShipMove() {
        if (map.getConfig().isBehaviorOption1Selected()) {
            return false;
        }

        float changeToSkip = (age / 100f);
        return Math.random() < Math.min(changeToSkip, 0.8);
    }

    public void move() {
        if (!shouldShipMove()) {
            direction = direction.rotate(genotype.getNextGene());

            Vector2d initialPosition = position;
            Vector2d newPosition = position.add(direction.toUnitVector());
            Vector2d validatedNewPosition = map.validateMove(initialPosition, newPosition);

            position = validatedNewPosition;
            direction = map.validateDirection(newPosition, direction);
            animalMoved(initialPosition, validatedNewPosition);
        }

        loseEnergy();
        age();
        incrementDaysLived();
        System.out.println("Animal stats: " + position + " " + energy + " " + age);
    }

    public void loseEnergy() {
        this.energy -= Math.min(map.getConfig().getLoseEnergyPerMove(), this.energy);
    }

    public void eat() {
        this.energy += map.getConfig().getEnergyProvidedByPlant();
        statistics.incrementPlantsEaten();
    }

    public void age() {
        age++;
    }

    public boolean canReproduce() {
        return energy >= map.getConfig().getEnergyToReproduce();
    }

    public void reproduce() {
        energy -= map.getConfig().getEnergyLoseAfterReproduction();
    }

    public static Animal reproduce(Animal parent1, Animal parent2) {
        if (!parent1.canReproduce() || !parent2.canReproduce() || !parent1.getPosition().equals(parent2.getPosition()) || !parent1.map.equals(parent2.map)) {
            System.err.println("Animals cannot reproduce");
            return null;
        }

        parent1.reproduce();
        parent2.reproduce();

        Genotype genotype = new Genotype(parent1, parent2);

        Animal child = new Animal(
                parent1.getPosition(),
                genotype,
                parent1.map,
                parent1.map.getConfig().getEnergyLoseAfterReproduction() * 2
        );

        parent1.addChild(child);
        parent2.addChild(child);

        return child;
    }

    public void subscribe(AnimalMovedListener listener) {
        listeners.add(listener);
    }

    private void animalMoved(Vector2d oldPosition, Vector2d newPosition) {
        for (AnimalMovedListener listener : listeners) {
            listener.animalMoved(oldPosition, newPosition, this);
        }
    }

    private static void sortAnimalsByEnergy(List<Animal> animals) {
        Comparator<Animal> energyComparator = Comparator.comparingInt(Animal::getEnergy);
        animals.sort(energyComparator);
    }

    public static void resolveConflict(List<Animal> animals, int animalsCount) {
        if (animals.size() == animalsCount) {
            return;
        }

        sortAnimalsByEnergy(animals);
    }
}