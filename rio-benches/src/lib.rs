#![allow(unused_imports, dead_code)]
#![cfg_attr(feature = "nightly", feature(test))]
use std::thread;

use crossbeam_channel::{bounded, Receiver, Sender};
#[cfg(feature = "nightly")]
extern crate test;
#[cfg(feature = "nightly")]
use test::Bencher;

#[derive(Copy, Clone)]
struct Data(pub [f64; 5]);

struct MethodCommunicator {
    int: f64,
    rec: Receiver<Data>,
    ext1: Sender<Data>,
    ext2: Sender<Data>,
}

impl MethodCommunicator {
    pub const fn new(a: f64, b: Receiver<Data>, c: Sender<Data>, d: Sender<Data>) -> Self {
        Self {
            int: a,
            rec: b,
            ext1: c,
            ext2: d,
        }
    }

    pub fn process(&mut self) {
        let mut a = self.int;
        self.rec.try_iter().for_each(|d| {
            a *= d.0[0];
        });
        self.int = a;
    }

    pub fn send(&self) {
        if self.int > 0. {
            self.ext1.try_send(Data([self.int; 5])).ok();
        } else {
            self.ext2.try_send(Data([self.int; 5])).ok();
        }
    }
}

const ITERS: usize = 100;

#[cfg(feature = "nightly")]
#[bench]
fn bench_iters_send_recv(b: &mut Bencher) {
    let (s1, r1) = bounded(1000);
    let (s2, r2) = bounded(1000);
    let (s3, r3) = bounded(1000);
    let (s4, r4) = bounded(1000);

    let a1 = MethodCommunicator::new(1.01, r1, s2.clone(), s3.clone());
    let a2 = MethodCommunicator::new(0.99, r2, s3.clone(), s4.clone());
    let a3 = MethodCommunicator::new(-0.89, r3, s4.clone(), s1.clone());
    let mut a4 = MethodCommunicator::new(-1.23, r4, s1.clone(), s2.clone());

    const ITER2: usize = 100 * ITERS;

    fn spawn_bench_thread(mut a: MethodCommunicator) -> thread::JoinHandle<()> {
        thread::spawn(move || {
            for _ in 0..ITER2 {
                a.process();
                a.send();
            }
        })
    }
    let t1 = spawn_bench_thread(a1);
    let t2 = spawn_bench_thread(a2);
    let t3 = spawn_bench_thread(a3);

    b.iter(|| {
        for _ in 0..ITERS {
            a4.send();
            a4.process();
        }
    });

    t1.join().unwrap();
    t2.join().unwrap();
    t3.join().unwrap();
}

#[cfg(not(feature = "nightly"))]
#[test]
fn test_non_nightly() {
    println!(
        "Designed to compiled with nightly (use the nightly feature) and run on the rio
    This is just so tests pass."
    );
}
