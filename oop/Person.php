<?php

class Person
{
    public int $age;

    public function setAge(int $age): void
    {
        $this->age= $age;
    }

    public function getAge(): int
    {
        return $this->age;
    }
}